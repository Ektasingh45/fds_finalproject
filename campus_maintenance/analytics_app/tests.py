import csv
import io
from datetime import datetime, timedelta

import pandas as pd
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile
from complaints.models import Category, Complaint
from complaints.tests import TEST_PASSWORD, make_complaint, make_user

from . import analysis

NOW = datetime(2026, 4, 1, 12, 0)
VALID_CSV = (
    "complaint_id,category,building,floor,room,priority,status,submitted_at,resolved_at\n"
    "H1,electrical,Main Block,2,204,medium,closed,2026-03-01 10:00,2026-03-02 10:00\n"
    "H2,electrical,main-block,2,204,high,closed,2026-03-10 09:00,2026-03-10 21:00\n"
    "H3,plumbing,Hostel A,1,Washroom,low,submitted,2026-03-15 08:00,\n"
)


def csv_upload(text, name="history.csv"):
    return SimpleUploadedFile(name, text.encode("utf-8"), content_type="text/csv")


# ---------------------------------------------------------------------------
# 13. CSV export
# ---------------------------------------------------------------------------
class ExportTests(TestCase):
    def setUp(self):
        self.admin = make_user("admin1", Profile.Role.ADMIN)
        self.student = make_user("student1", Profile.Role.STUDENT)
        self.staff = make_user("staff1", Profile.Role.STAFF)
        self.complaint = make_complaint(self.student, worker=self.staff)

    def test_admin_can_export_csv(self):
        self.client.login(username="admin1", password=TEST_PASSWORD)
        response = self.client.get(reverse("export_csv"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertIn("attachment", response["Content-Disposition"])
        rows = list(csv.reader(io.StringIO(response.content.decode())))
        self.assertEqual(rows[0][0], "complaint_id")
        self.assertEqual(rows[1][0], self.complaint.reference_id)
        self.assertEqual(rows[1][9], "staff1")

    def test_export_respects_filters(self):
        make_complaint(self.student, category=Category.OTHER, title="Other issue here")
        self.client.login(username="admin1", password=TEST_PASSWORD)
        response = self.client.get(reverse("export_csv"), {"view": "open"})  # the unassigned "Other" one
        rows = list(csv.reader(io.StringIO(response.content.decode())))
        self.assertEqual(len(rows), 2)  # header + 1 row
        self.assertEqual(rows[1][7], "Open")

    def test_student_and_staff_cannot_export(self):
        for username in ["student1", "staff1"]:
            self.client.login(username=username, password=TEST_PASSWORD)
            self.assertEqual(self.client.get(reverse("export_csv")).status_code, 403)

    def test_anonymous_cannot_export(self):
        response = self.client.get(reverse("export_csv"))
        self.assertEqual(response.status_code, 302)

    def test_formula_values_are_neutralised(self):
        Complaint.objects.filter(pk=self.complaint.pk).update(title="=HYPERLINK(\"http://evil\")")
        self.client.login(username="admin1", password=TEST_PASSWORD)
        response = self.client.get(reverse("export_csv"))
        rows = list(csv.reader(io.StringIO(response.content.decode())))
        self.assertTrue(rows[1][1].startswith("'="))


# ---------------------------------------------------------------------------
# 14. Historical CSV validation
# ---------------------------------------------------------------------------
class HistoricalCSVTests(TestCase):
    def setUp(self):
        self.admin = make_user("admin1", Profile.Role.ADMIN)
        self.student = make_user("student1", Profile.Role.STUDENT)

    def load(self, text, name="history.csv"):
        return analysis.load_historical_csv(csv_upload(text, name), max_bytes=1024 * 1024, max_rows=1000)

    def test_valid_csv_loads(self):
        df, warnings = self.load(VALID_CSV)
        self.assertEqual(len(df), 3)
        self.assertEqual(warnings, [])

    def test_missing_columns_rejected(self):
        with self.assertRaisesMessage(analysis.CSVValidationError, "Missing required column(s): priority, status"):
            self.load("complaint_id,category,building,submitted_at\nH1,electrical,Main,2026-01-01\n")

    def test_wrong_extension_rejected(self):
        with self.assertRaisesMessage(analysis.CSVValidationError, ".csv"):
            self.load(VALID_CSV, name="history.xlsx")

    def test_empty_file_rejected(self):
        with self.assertRaisesMessage(analysis.CSVValidationError, "empty"):
            self.load("")

    def test_header_only_rejected(self):
        with self.assertRaisesMessage(analysis.CSVValidationError, "no data rows"):
            self.load("complaint_id,category,building,priority,status,submitted_at\n")

    def test_file_too_large_rejected(self):
        with self.assertRaisesMessage(analysis.CSVValidationError, "too large"):
            analysis.load_historical_csv(csv_upload(VALID_CSV), max_bytes=10, max_rows=1000)

    def test_invalid_values_are_handled(self):
        text = (
            "complaint_id,category,building,priority,status,submitted_at,resolved_at\n"
            "H1,electrical,Main,medium,closed,2026-03-01 10:00,2026-03-02 10:00\n"
            "H2,,Main,medium,closed,2026-03-01 10:00,\n"                  # missing category
            "H3,plumbing,Main,medium,closed,not a date,\n"                 # bad submitted date
            "H4,plumbing,Main,critical,done,2026-03-05 10:00,yesterday\n"  # bad priority, status, resolved
            "H5,plumbing,Main,low,closed,2026-03-05 10:00,2026-03-01 10:00\n"  # resolved before submitted
        )
        df, warnings = self.load(text)
        self.assertEqual(len(df), 3)
        self.assertEqual(df.loc[df["reference_id"] == "H4", "priority"].iloc[0], "unknown")
        self.assertEqual(df.loc[df["reference_id"] == "H4", "status"].iloc[0], "unknown")
        self.assertTrue(pd.isna(df.loc[df["reference_id"] == "H5", "resolved_at"].iloc[0]))
        joined = " ".join(warnings)
        self.assertIn("2 row(s) were skipped", joined)
        self.assertIn("could not be read", joined)
        self.assertIn("before the submitted date", joined)
        self.assertIn("Optional column 'floor'", joined)

    def test_all_rows_invalid_rejected(self):
        text = "complaint_id,category,building,priority,status,submitted_at\nH1,,Main,low,closed,bad\n"
        with self.assertRaisesMessage(analysis.CSVValidationError, "No valid rows"):
            self.load(text)

    def test_non_utf8_rejected(self):
        upload = SimpleUploadedFile("h.csv", "complaint_id,category\nH1,é\n".encode("utf-16"), content_type="text/csv")
        with self.assertRaisesMessage(analysis.CSVValidationError, "UTF-8"):
            analysis.load_historical_csv(upload, max_bytes=1024 * 1024, max_rows=1000)

    def test_upload_view_shows_report_and_saves_nothing(self):
        self.client.login(username="admin1", password=TEST_PASSWORD)
        response = self.client.post(
            reverse("historical_upload"), {"csv_file": csv_upload(VALID_CSV), "days": 30, "min_complaints": 2}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["report"]["total"], 3)
        self.assertEqual(Complaint.objects.count(), 0)  # nothing inserted into the live database

    def test_upload_view_shows_error_for_bad_columns(self):
        self.client.login(username="admin1", password=TEST_PASSWORD)
        response = self.client.post(
            reverse("historical_upload"),
            {"csv_file": csv_upload("a,b\n1,2\n"), "days": 30, "min_complaints": 2},
        )
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Missing required column", status_code=400)

    def test_student_cannot_upload(self):
        self.client.login(username="student1", password=TEST_PASSWORD)
        response = self.client.post(reverse("historical_upload"), {"csv_file": csv_upload(VALID_CSV)})
        self.assertEqual(response.status_code, 403)

    def test_sample_csv_file_is_valid(self):
        from django.conf import settings
        path = settings.BASE_DIR / "static" / "samples" / "historical_complaints_sample.csv"
        with open(path, "rb") as sample:
            upload = SimpleUploadedFile("historical_complaints_sample.csv", sample.read())
        df, warnings = analysis.load_historical_csv(upload, max_bytes=1024 * 1024, max_rows=1000)
        self.assertEqual(len(df), 30)  # two rows in the sample are deliberately invalid
        self.assertTrue(len(warnings) > 0)


# ---------------------------------------------------------------------------
# 15. Analytics with empty or incomplete data
# ---------------------------------------------------------------------------
class AnalysisTests(TestCase):
    def test_empty_dataset_report(self):
        df = analysis.records_to_dataframe([])
        report = analysis.build_report(df, NOW)
        self.assertEqual(report["total"], 0)
        self.assertEqual(report["by_category"], [])
        self.assertIsNone(report["resolution"])
        self.assertEqual(report["charts"], {})

    def test_incomplete_dataset_without_resolved_dates(self):
        records = [
            {"category": "electrical", "building": "Main", "floor": "", "room": "", "priority": "low",
             "status": "submitted", "submitted_at": datetime(2026, 3, 1, 9, 0)},
            {"category": "plumbing", "building": "Hostel", "priority": "", "status": "assigned",
             "submitted_at": datetime(2026, 3, 20, 9, 0)},
        ]
        df = analysis.records_to_dataframe(records)
        report = analysis.build_report(df, NOW)
        self.assertEqual(report["total"], 2)
        self.assertIsNone(report["resolution"])  # no resolved complaints
        self.assertEqual(report["overdue"]["overdue_count"], 1)  # low = 7 days, the blank priority has no deadline
        self.assertIn("category", report["charts"])

    def test_statistics_values(self):
        df, _ = analysis.clean_historical_dataframe(pd.read_csv(io.StringIO(VALID_CSV), dtype=str), max_rows=100)
        report = analysis.build_report(df, NOW, include_charts=False)
        self.assertEqual(report["by_category"][0], {"name": "electrical", "count": 2, "percent": 66.7})
        self.assertEqual(report["resolution"]["average_hours"], 18.0)  # (24 + 12) / 2
        self.assertEqual(report["resolution"]["median_hours"], 18.0)
        self.assertEqual(report["overdue"]["overdue_count"], 1)  # H3: low priority, 17 days old
        self.assertEqual(report["monthly"], [{"month": "Mar 2026", "submitted": 3, "resolved": 2}])

    def test_recurring_patterns_use_normalised_location(self):
        df, _ = analysis.clean_historical_dataframe(pd.read_csv(io.StringIO(VALID_CSV), dtype=str), max_rows=100)
        patterns = analysis.find_recurring_patterns(df, window_days=30, min_complaints=2)
        self.assertEqual(len(patterns), 1)  # "Main Block" and "main-block" are the same place
        self.assertEqual(patterns[0]["category"], "electrical")
        self.assertEqual(patterns[0]["most_in_window"], 2)

    def test_recurring_patterns_respect_window(self):
        df, _ = analysis.clean_historical_dataframe(pd.read_csv(io.StringIO(VALID_CSV), dtype=str), max_rows=100)
        self.assertEqual(analysis.find_recurring_patterns(df, window_days=5, min_complaints=2), [])

    def test_analytics_page_with_no_complaints(self):
        make_user("admin1", Profile.Role.ADMIN)
        self.client.login(username="admin1", password=TEST_PASSWORD)
        response = self.client.get(reverse("analytics_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No data to analyse yet")

    def test_analytics_page_with_live_data(self):
        make_user("admin1", Profile.Role.ADMIN)
        student = make_user("student1", Profile.Role.STUDENT)
        make_complaint(student)
        resolved = make_complaint(student, title="Second fan")
        Complaint.objects.filter(pk=resolved.pk).update(
            status="resolved", resolved_at=resolved.submitted_at + timedelta(hours=5)
        )
        self.client.login(username="admin1", password=TEST_PASSWORD)
        response = self.client.get(reverse("analytics_dashboard"))
        report = response.context["report"]
        self.assertEqual(report["total"], 2)
        self.assertEqual(report["resolution"]["average_hours"], 5.0)
        self.assertTrue(report["charts"]["monthly"].startswith("data:image/png;base64,"))

    def test_analytics_page_shows_only_charts(self):
        make_user("admin1", Profile.Role.ADMIN)
        student = make_user("student1", Profile.Role.STUDENT)
        make_complaint(student)
        self.client.login(username="admin1", password=TEST_PASSWORD)
        response = self.client.get(reverse("analytics_dashboard"))
        self.assertContains(response, 'src="data:image/png;base64,', count=4)
        self.assertNotContains(response, "<table")
        self.assertNotContains(response, "Most reported locations")
        self.assertNotContains(response, "Potential recurring patterns")
