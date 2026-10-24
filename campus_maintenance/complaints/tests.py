"""
Tests for complaint submission, automatic rules, permissions and status tracking.
Run with:  python manage.py test
"""
import io
import shutil
import tempfile
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from accounts.models import Profile

from . import services
from .models import (
    Category,
    Complaint,
    ComplaintStatusHistory,
    Priority,
    PriorityDeadline,
    ReopenRequest,
    Status,
)

TEST_PASSWORD = "TestPass#12345"
TEMP_MEDIA = tempfile.mkdtemp()


# ---------------------------------------------------------------------------
# Helpers (also imported by analytics_app/tests.py)
# ---------------------------------------------------------------------------
def make_user(username, role, is_active=True):
    user = User.objects.create_user(username=username, password=TEST_PASSWORD, is_active=is_active)
    Profile.objects.create(user=user, role=role)
    return user


def make_complaint(reporter, category=Category.ELECTRICAL, urgency=Priority.MEDIUM, worker=None, **extra):
    """
    Create a complaint through the real service so all rules run.
    If `worker` is given, the complaint is then assigned to them, as the
    administrator would do (so it becomes In Progress).
    """
    complaint = Complaint(
        title=extra.pop("title", "Fan not working"),
        description=extra.pop("description", "The ceiling fan does not turn on at all."),
        category=category,
        building=extra.pop("building", "Main Block"),
        floor=extra.pop("floor", "2"),
        room=extra.pop("room", "204"),
        reported_urgency=urgency,
    )
    complaint = services.submit_complaint(complaint, reporter)
    if worker is not None:
        services.assign_complaint(complaint, worker, None)
    return complaint


def tiny_png(name="photo.png"):
    buffer = io.BytesIO()
    Image.new("RGB", (10, 10), color="blue").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


def valid_form_data(**changes):
    data = {
        "title": "Tube light not working",
        "description": "The tube light near the whiteboard is not working.",
        "category": Category.ELECTRICAL,
        "building": "  main   block ",
        "floor": "2",
        "room": "204",
        "reported_urgency": Priority.MEDIUM,
    }
    data.update(changes)
    return data


class BaseTestCase(TestCase):
    def setUp(self):
        self.student = make_user("student1", Profile.Role.STUDENT)
        self.other_student = make_user("student2", Profile.Role.STUDENT)
        self.faculty = make_user("faculty1", Profile.Role.FACULTY)
        self.electrician = make_user("electrician", Profile.Role.STAFF)
        self.plumber = make_user("plumber", Profile.Role.STAFF)
        self.admin = make_user("admin1", Profile.Role.ADMIN)

    def login(self, user):
        self.client.login(username=user.username, password=TEST_PASSWORD)


# ---------------------------------------------------------------------------
# 1, 2, 12. Submission, reference IDs, invalid forms and uploads
# ---------------------------------------------------------------------------
@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class ComplaintSubmissionTests(BaseTestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)
        super().tearDownClass()

    def test_valid_submission_creates_complaint(self):
        self.login(self.student)
        response = self.client.post(reverse("complaint_create"), valid_form_data())
        complaint = Complaint.objects.get()
        self.assertRedirects(response, reverse("complaint_submitted", args=[complaint.pk]))
        self.assertEqual(complaint.reporter, self.student)
        self.assertEqual(complaint.building, "Main Block")  # extra spaces removed, title case
        self.assertTrue(complaint.reference_id.startswith("CMP-"))

    def test_valid_submission_with_photo(self):
        self.login(self.student)
        data = valid_form_data()
        data["photo"] = tiny_png()
        self.client.post(reverse("complaint_create"), data)
        complaint = Complaint.objects.get()
        self.assertTrue(complaint.photo.name.startswith("complaint_photos/"))
        self.assertNotIn("photo.png", complaint.photo.name)  # stored with a random name

    def test_reference_ids_are_unique(self):
        first = make_complaint(self.student)
        second = make_complaint(self.student)
        third = make_complaint(self.faculty)
        ids = {first.reference_id, second.reference_id, third.reference_id}
        self.assertEqual(len(ids), 3)
        year = timezone.now().year
        self.assertEqual(first.reference_id, f"CMP-{year}-{first.pk:05d}")

    def test_missing_fields_are_rejected(self):
        self.login(self.student)
        response = self.client.post(reverse("complaint_create"), valid_form_data(title="", building=""))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Complaint.objects.count(), 0)
        self.assertContains(response, "This field is required")

    def test_too_short_description_is_rejected(self):
        self.login(self.student)
        response = self.client.post(reverse("complaint_create"), valid_form_data(description="bad"))
        self.assertContains(response, "at least 10 characters")
        self.assertEqual(Complaint.objects.count(), 0)

    def test_invalid_category_and_urgency_are_rejected(self):
        self.login(self.student)
        response = self.client.post(
            reverse("complaint_create"), valid_form_data(category="spaceship", reported_urgency="extreme")
        )
        self.assertEqual(Complaint.objects.count(), 0)
        self.assertContains(response, "Select a valid choice", count=2)

    def test_non_image_upload_is_rejected(self):
        self.login(self.student)
        data = valid_form_data()
        data["photo"] = SimpleUploadedFile("virus.png", b"this is not an image", content_type="image/png")
        response = self.client.post(reverse("complaint_create"), data)
        self.assertEqual(Complaint.objects.count(), 0)
        self.assertContains(response, "Upload a valid image")

    def test_wrong_file_extension_is_rejected(self):
        self.login(self.student)
        data = valid_form_data()
        buffer = io.BytesIO()
        Image.new("RGB", (10, 10)).save(buffer, format="GIF")
        data["photo"] = SimpleUploadedFile("anim.gif", buffer.getvalue(), content_type="image/gif")
        response = self.client.post(reverse("complaint_create"), data)
        self.assertEqual(Complaint.objects.count(), 0)
        self.assertContains(response, "File extension")

    @override_settings(MAX_PHOTO_SIZE_MB=0)
    def test_oversized_photo_is_rejected(self):
        self.login(self.student)
        data = valid_form_data()
        data["photo"] = tiny_png()
        response = self.client.post(reverse("complaint_create"), data)
        self.assertEqual(Complaint.objects.count(), 0)
        self.assertContains(response, "must be smaller than")

    def test_staff_cannot_submit_complaints(self):
        self.login(self.electrician)
        response = self.client.post(reverse("complaint_create"), valid_form_data())
        self.assertEqual(response.status_code, 403)

    def test_anonymous_user_is_sent_to_login(self):
        response = self.client.get(reverse("complaint_create"))
        self.assertRedirects(response, reverse("login") + "?next=" + reverse("complaint_create"))


# ---------------------------------------------------------------------------
# 3, 4. Assignment (by the administrator only)
# ---------------------------------------------------------------------------
class AssignmentTests(BaseTestCase):
    def test_new_complaint_is_never_assigned_automatically(self):
        for category in [Category.ELECTRICAL, Category.PLUMBING, Category.NETWORK, Category.OTHER]:
            complaint = make_complaint(self.student, category=category, title=f"Problem {category}")
            self.assertIsNone(complaint.assigned_to, category)
            self.assertEqual(complaint.status, Status.SUBMITTED, category)
            self.assertEqual(complaint.tracking_label, "Open", category)

    def test_submission_history_says_waiting_for_admin(self):
        complaint = make_complaint(self.student)
        self.assertEqual(complaint.history.count(), 1)
        self.assertIn("Waiting for the administrator to assign", complaint.history.get().note)

    def test_unassigned_complaint_is_open_on_admin_dashboard(self):
        complaint = make_complaint(self.student, category=Category.OTHER)
        self.login(self.admin)
        response = self.client.get(reverse("admin_dashboard"))
        self.assertIn(complaint, response.context["open_complaints"])
        self.assertEqual(response.context["open_count"], 1)

    def test_admin_can_assign_manually(self):
        complaint = make_complaint(self.student, category=Category.OTHER)
        self.login(self.admin)
        self.client.post(reverse("admin_assign", args=[complaint.pk]), {"staff": self.plumber.pk, "note": ""})
        complaint.refresh_from_db()
        self.assertEqual(complaint.assigned_to, self.plumber)
        self.assertEqual(complaint.status, Status.ASSIGNED)

    def test_quick_assign_from_dashboard_returns_to_dashboard(self):
        complaint = make_complaint(self.student, category=Category.OTHER)
        self.login(self.admin)
        dashboard = self.client.get(reverse("admin_dashboard"))
        self.assertIn(self.plumber, dashboard.context["assignable_staff"])
        response = self.client.post(
            reverse("admin_assign", args=[complaint.pk]), {"staff": self.plumber.pk, "return_to": "dashboard"}
        )
        self.assertRedirects(response, reverse("admin_dashboard"))
        complaint.refresh_from_db()
        self.assertEqual(complaint.assigned_to, self.plumber)

    def test_unavailable_worker_not_in_dropdown(self):
        complaint = make_complaint(self.student, category=Category.OTHER)
        self.plumber.is_active = False
        self.plumber.save()
        self.login(self.admin)
        self.assertNotIn(self.plumber, self.client.get(reverse("admin_dashboard")).context["assignable_staff"])
        self.client.post(reverse("admin_assign", args=[complaint.pk]), {"staff": self.plumber.pk})
        complaint.refresh_from_db()
        self.assertIsNone(complaint.assigned_to)

    def test_admin_can_reassign(self):
        complaint = make_complaint(self.student, category=Category.ELECTRICAL, worker=self.electrician)
        self.login(self.admin)
        self.client.post(reverse("admin_assign", args=[complaint.pk]), {"staff": self.plumber.pk})
        complaint.refresh_from_db()
        self.assertEqual(complaint.assigned_to, self.plumber)
        self.assertIn("Assigned to", complaint.history.last().note)


# ---------------------------------------------------------------------------
# 5. Priority and deadline rules
# ---------------------------------------------------------------------------
class PriorityAndDeadlineTests(BaseTestCase):
    def test_reported_urgency_is_used(self):
        priority, review, _ = services.calculate_priority(Category.FURNITURE, Priority.LOW, "Chair", "Chair is loose")
        self.assertEqual(priority, Priority.LOW)
        self.assertFalse(review)

    def test_category_minimum_raises_low_to_medium(self):
        priority, _, _ = services.calculate_priority(Category.ELECTRICAL, Priority.LOW, "Switch", "Switch is loose")
        self.assertEqual(priority, Priority.MEDIUM)

    def test_safety_keyword_makes_urgent_and_flags_review(self):
        priority, review, reasons = services.calculate_priority(
            Category.ELECTRICAL, Priority.LOW, "Switch board", "Sparks and a burning smell from the switch"
        )
        self.assertEqual(priority, Priority.URGENT)
        self.assertTrue(review)
        self.assertTrue(any("spark" in reason for reason in reasons))

    def test_reporter_urgent_is_flagged_for_review(self):
        priority, review, _ = services.calculate_priority(Category.NETWORK, Priority.URGENT, "No internet", "Wifi down")
        self.assertEqual(priority, Priority.URGENT)
        self.assertTrue(review)

    def test_unknown_urgency_falls_back_to_medium(self):
        priority, _, _ = services.calculate_priority(Category.FURNITURE, "extreme", "Desk", "Desk is loose")
        self.assertEqual(priority, Priority.MEDIUM)

    def test_default_deadline_hours(self):
        start = timezone.now()
        self.assertEqual(services.calculate_deadline(Priority.URGENT, start), start + timedelta(hours=4))
        self.assertEqual(services.calculate_deadline(Priority.HIGH, start), start + timedelta(hours=24))
        self.assertEqual(services.calculate_deadline(Priority.MEDIUM, start), start + timedelta(hours=72))
        self.assertEqual(services.calculate_deadline(Priority.LOW, start), start + timedelta(days=7))

    def test_configured_deadline_is_used(self):
        PriorityDeadline.objects.create(priority=Priority.MEDIUM, target_hours=10)
        complaint = make_complaint(self.student, urgency=Priority.MEDIUM)
        self.assertEqual(complaint.deadline, complaint.submitted_at + timedelta(hours=10))

    def test_rules_and_deadline_pages_are_removed(self):
        self.login(self.admin)
        self.assertEqual(self.client.get("/complaints/admin/mappings/").status_code, 404)
        self.assertEqual(self.client.get("/complaints/admin/deadlines/").status_code, 404)
        response = self.client.get(reverse("admin_dashboard"))
        self.assertNotContains(response, "Assignment Rules")
        self.assertNotContains(response, ">Deadlines<")

    def test_removed_admin_actions_and_workers_page(self):
        complaint = make_complaint(self.student)
        self.login(self.admin)
        for url in [f"/complaints/{complaint.pk}/priority/", f"/complaints/{complaint.pk}/close/",
                    f"/complaints/{complaint.pk}/safety-reviewed/", "/staff/", "/staff/new/"]:
            self.assertEqual(self.client.post(url).status_code, 404, url)
        self.assertNotContains(self.client.get(reverse("admin_dashboard")), ">Workers<")


# ---------------------------------------------------------------------------
# 6, 7. Access restrictions
# ---------------------------------------------------------------------------
class AccessControlTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.complaint = make_complaint(self.student, category=Category.ELECTRICAL, worker=self.electrician)

    def test_reporter_can_view_own_complaint(self):
        self.login(self.student)
        response = self.client.get(reverse("complaint_detail", args=[self.complaint.pk]))
        self.assertEqual(response.status_code, 200)

    def test_student_cannot_view_other_students_complaint(self):
        self.login(self.other_student)
        response = self.client.get(reverse("complaint_detail", args=[self.complaint.pk]))
        self.assertEqual(response.status_code, 404)

    def test_student_dashboard_lists_only_own_complaints(self):
        make_complaint(self.other_student, title="Other student issue")
        self.login(self.student)
        response = self.client.get(reverse("reporter_dashboard"))
        self.assertEqual(list(response.context["complaints"]), [self.complaint])

    def test_student_cannot_change_status(self):
        self.login(self.student)
        response = self.client.post(
            reverse("admin_update_progress", args=[self.complaint.pk]),
            {"action": "close", "note": "Fixed it myself"},
        )
        self.assertEqual(response.status_code, 403)
        self.complaint.refresh_from_db()
        self.assertEqual(self.complaint.status, Status.ASSIGNED)

    def test_student_cannot_open_admin_pages(self):
        self.login(self.student)
        for name in ["admin_dashboard", "admin_complaint_list"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)

    def test_worker_account_has_no_access(self):
        # Even if a worker session existed, workers can see nothing.
        self.login(self.electrician)
        response = self.client.get(reverse("complaint_detail", args=[self.complaint.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.get(reverse("admin_dashboard")).status_code, 403)
        self.assertEqual(self.client.get(reverse("reporter_dashboard")).status_code, 403)
        response = self.client.post(
            reverse("admin_update_progress", args=[self.complaint.pk]), {"action": "close", "note": "x"}
        )
        self.assertEqual(response.status_code, 403)
        response = self.client.post(reverse("admin_assign", args=[self.complaint.pk]), {"staff": self.plumber.pk})
        self.assertEqual(response.status_code, 403)
        self.complaint.refresh_from_db()
        self.assertEqual(self.complaint.status, Status.ASSIGNED)
        self.assertEqual(self.complaint.assigned_to, self.electrician)

    def test_admin_can_view_any_complaint(self):
        self.login(self.admin)
        response = self.client.get(reverse("complaint_detail", args=[self.complaint.pk]))
        self.assertEqual(response.status_code, 200)


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class PhotoAccessTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        complaint = Complaint(
            title="Broken switch", description="The switch is broken and hanging.", category=Category.ELECTRICAL,
            building="Main Block", floor="1", room="101", reported_urgency=Priority.MEDIUM, photo=tiny_png(),
        )
        self.complaint = services.submit_complaint(complaint, self.student)

    def test_owner_can_see_photo(self):
        self.login(self.student)
        response = self.client.get(reverse("complaint_photo", args=[self.complaint.pk, "issue"]))
        self.assertEqual(response.status_code, 200)
        response.close()

    def test_other_student_cannot_see_photo(self):
        self.login(self.other_student)
        response = self.client.get(reverse("complaint_photo", args=[self.complaint.pk, "issue"]))
        self.assertEqual(response.status_code, 404)

    def test_anonymous_cannot_see_photo(self):
        response = self.client.get(reverse("complaint_photo", args=[self.complaint.pk, "issue"]))
        self.assertEqual(response.status_code, 302)


# ---------------------------------------------------------------------------
# 8, 9. Status updates and history
# ---------------------------------------------------------------------------
@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class ProgressUpdateTests(BaseTestCase):
    """Assigned complaints are In Progress; the administrator closes them."""

    def setUp(self):
        super().setUp()
        self.complaint = make_complaint(self.student, category=Category.ELECTRICAL, worker=self.electrician)
        self.login(self.admin)
        self.update_url = reverse("admin_update_progress", args=[self.complaint.pk])

    def test_assigned_complaint_shows_as_in_progress(self):
        self.assertEqual(self.complaint.tracking_label, "In Progress")
        unassigned = make_complaint(self.student, category=Category.OTHER, title="Notice board fallen")
        self.assertEqual(unassigned.tracking_label, "Open")

    def test_admin_closes_complaint(self):
        data = {"action": "close", "note": "Replaced the capacitor", "resolution_photo": tiny_png()}
        self.client.post(self.update_url, data)
        self.complaint.refresh_from_db()
        self.assertEqual(self.complaint.status, Status.RESOLVED)  # shown as "Closed" to the admin
        self.assertEqual(self.complaint.tracking_label, "Closed")
        self.assertIsNotNone(self.complaint.resolved_at)
        self.assertEqual(self.complaint.resolution_notes, "Replaced the capacitor")
        self.assertTrue(self.complaint.resolution_photo)

    def test_closing_requires_notes(self):
        response = self.client.post(self.update_url, {"action": "close", "note": ""})
        self.assertContains(response, "write what was done, or why it is being closed")
        self.complaint.refresh_from_db()
        self.assertEqual(self.complaint.status, Status.ASSIGNED)

    def test_unknown_action_is_rejected(self):
        response = self.client.post(self.update_url, {"action": "in_progress", "note": "done"})
        self.assertContains(response, "Select a valid choice")
        self.complaint.refresh_from_db()
        self.assertEqual(self.complaint.status, Status.ASSIGNED)

    def test_open_complaint_can_be_closed(self):
        open_complaint = make_complaint(self.student, category=Category.OTHER, title="Notice board fallen")
        detail = self.client.get(reverse("complaint_detail", args=[open_complaint.pk]))
        self.assertIn("progress_form", detail.context)  # Close is offered for Open complaints too
        self.client.post(
            reverse("admin_update_progress", args=[open_complaint.pk]),
            {"action": "close", "note": "Duplicate of another complaint"},
        )
        open_complaint.refresh_from_db()
        self.assertEqual(open_complaint.tracking_label, "Closed")
        self.assertIsNone(open_complaint.assigned_to)

    def test_reopening_a_closed_open_complaint_returns_to_open(self):
        open_complaint = make_complaint(self.student, category=Category.OTHER, title="Notice board fallen")
        services.change_status(open_complaint, Status.RESOLVED, self.admin, "Closed without a worker")
        reopen_request = services.create_reopen_request(open_complaint, self.student, "It is still lying on the floor.")
        services.review_reopen_request(reopen_request, self.admin, approve=True)
        open_complaint.refresh_from_db()
        self.assertEqual(open_complaint.tracking_label, "Open")
        self.assertIsNone(open_complaint.resolved_at)

    def test_detail_page_shows_only_assign_and_close(self):
        response = self.client.get(reverse("complaint_detail", args=[self.complaint.pk]))
        self.assertIn("assign_form", response.context)
        self.assertIn("progress_form", response.context)
        self.assertContains(response, "Select a worker")
        self.assertContains(response, "Close complaint")
        for removed in ["priority_form", "close_form", "safety_form"]:
            self.assertNotIn(removed, response.context)
        # Only the three tracking words appear as status badges
        self.assertContains(response, 'class="badge track-in_progress">In Progress<')
        self.assertNotContains(response, ">Assigned<")

    def test_invalid_transition_raises_error(self):
        with self.assertRaises(services.InvalidTransition):
            services.change_status(self.complaint, Status.REOPENED, self.electrician, "no")

    def test_status_change_is_recorded_in_history(self):
        self.client.post(self.update_url, {"action": "close", "note": "Fixed the fan"})
        entry = ComplaintStatusHistory.objects.filter(complaint=self.complaint).last()
        self.assertEqual(entry.old_status, Status.ASSIGNED)
        self.assertEqual(entry.new_status, Status.RESOLVED)
        self.assertEqual(entry.changed_by, self.admin)
        self.assertEqual(entry.note, "Fixed the fan")
        self.assertIsNotNone(entry.created_at)

    def test_submission_and_assignment_are_recorded(self):
        complaint = make_complaint(self.student, title="Light not working")
        self.client.post(reverse("admin_assign", args=[complaint.pk]), {"staff": self.electrician.pk})
        statuses = list(complaint.history.values_list("old_status", "new_status"))
        self.assertEqual(statuses, [("", Status.SUBMITTED), (Status.SUBMITTED, Status.ASSIGNED)])
        self.assertEqual(complaint.history.last().changed_by, self.admin)  # assigned by the admin

    def test_work_note_without_status_change(self):
        self.client.post(self.update_url, {"action": "", "note": "Waiting for spare part"})
        entry = self.complaint.history.last()
        self.assertEqual(entry.note, "Waiting for spare part")
        self.assertEqual(entry.old_status, entry.new_status)

    def test_empty_update_is_rejected(self):
        response = self.client.post(self.update_url, {"action": "", "note": ""})
        self.assertContains(response, "Write a work note, or choose Close")


# ---------------------------------------------------------------------------
# 10. Overdue identification
# ---------------------------------------------------------------------------
class OverdueTests(BaseTestCase):
    def test_past_deadline_open_complaint_is_overdue(self):
        complaint = make_complaint(self.student)
        Complaint.objects.filter(pk=complaint.pk).update(deadline=timezone.now() - timedelta(hours=1))
        complaint.refresh_from_db()
        self.assertTrue(complaint.is_overdue)
        self.assertIn(complaint, Complaint.objects.filter(services.overdue_filter()))

    def test_future_deadline_is_not_overdue(self):
        complaint = make_complaint(self.student)
        self.assertFalse(complaint.is_overdue)
        self.assertEqual(Complaint.objects.filter(services.overdue_filter()).count(), 0)

    def test_resolved_complaint_is_never_overdue(self):
        complaint = make_complaint(self.student)
        services.change_status(complaint, Status.RESOLVED, self.electrician, "Fixed")
        Complaint.objects.filter(pk=complaint.pk).update(deadline=timezone.now() - timedelta(days=3))
        complaint.refresh_from_db()
        self.assertFalse(complaint.is_overdue)
        self.assertEqual(Complaint.objects.filter(services.overdue_filter()).count(), 0)

    def test_dashboard_boxes_open_matching_lists(self):
        open_one = make_complaint(self.student, category=Category.OTHER, title="Notice board fallen")
        working = make_complaint(self.student, title="Fan not working", worker=self.electrician)
        reopened = make_complaint(self.student, title="Light flickering", worker=self.electrician)
        services.change_status(reopened, Status.RESOLVED, self.admin, "Fixed")
        services.change_status(reopened, Status.REOPENED, self.admin, "Still flickering")
        done = make_complaint(self.student, title="Fixed fan")
        services.change_status(done, Status.RESOLVED, self.admin, "Fixed")
        confirmed = make_complaint(self.student, title="Fixed tap")
        services.change_status(confirmed, Status.RESOLVED, self.admin, "Fixed")
        services.confirm_resolution(confirmed, self.student)
        self.login(self.admin)

        dashboard = self.client.get(reverse("admin_dashboard"))
        list_url = reverse("admin_complaint_list")
        expected = {
            "open": ({open_one.pk}, "open_count"),
            "in_progress": ({working.pk, reopened.pk}, "in_progress_count"),
            "closed": ({done.pk, confirmed.pk}, "closed_count"),
        }
        for view, (pks, count_key) in expected.items():
            self.assertContains(dashboard, f"{list_url}?view={view}")
            response = self.client.get(list_url, {"view": view})
            self.assertEqual({c.pk for c in response.context["complaints"]}, pks, view)
            # The list shows exactly as many complaints as the box says.
            self.assertEqual(dashboard.context[count_key], len(pks), view)
        self.assertContains(self.client.get(list_url, {"view": "in_progress"}), "<h1>In Progress complaints</h1>")
        self.assertEqual(len(self.client.get(list_url).context["complaints"]), 5)

    def test_admin_lists_are_newest_first_with_close_buttons(self):
        older = make_complaint(self.student, title="Older complaint")
        newer = make_complaint(self.student, title="Newer complaint")
        Complaint.objects.filter(pk=older.pk).update(submitted_at=timezone.now() - timedelta(days=3))
        working_old = make_complaint(self.student, title="Working old", worker=self.electrician)
        working_new = make_complaint(self.student, title="Working new", worker=self.electrician)
        Complaint.objects.filter(pk=working_old.pk).update(submitted_at=timezone.now() - timedelta(days=2))
        self.login(self.admin)

        dashboard = self.client.get(reverse("admin_dashboard"))
        self.assertEqual([c.pk for c in dashboard.context["open_complaints"]], [newer.pk, older.pk])
        self.assertEqual([c.pk for c in dashboard.context["in_progress"]], [working_new.pk, working_old.pk])
        all_list = self.client.get(reverse("admin_complaint_list")).context["complaints"]
        self.assertEqual([c.pk for c in all_list], [working_new.pk, newer.pk, working_old.pk, older.pk])
        for complaint in [older, newer, working_old, working_new]:
            self.assertContains(dashboard, reverse("complaint_detail", args=[complaint.pk]) + "#close")

    def test_admin_sees_low_medium_high_priority(self):
        low = make_complaint(self.student, category=Category.FURNITURE, urgency=Priority.LOW, title="Loose chair")
        medium = make_complaint(self.student, urgency=Priority.MEDIUM, title="Fan not working")
        high = make_complaint(self.student, urgency=Priority.HIGH, title="No power in lab")
        urgent = make_complaint(self.student, title="Sparks from socket", description="Sparks fly from the socket.")
        self.assertEqual(urgent.priority, Priority.URGENT)
        self.assertEqual(urgent.admin_priority_label, "High")  # Urgent is shown as High to the admin
        self.login(self.admin)

        list_url = reverse("admin_complaint_list")
        response = self.client.get(list_url)
        for label in ["Low", "Medium", "High"]:
            self.assertContains(response, f'">{label}</span>')
        self.assertNotContains(response, ">Urgent<")
        expected = {"low": {low.pk}, "medium": {medium.pk}, "high": {high.pk, urgent.pk}}
        for level, pks in expected.items():
            response = self.client.get(list_url, {"priority": level})
            self.assertEqual({c.pk for c in response.context["complaints"]}, pks, level)
        detail = self.client.get(reverse("complaint_detail", args=[urgent.pk]))
        self.assertContains(detail, "High priority")

    def test_admin_pages_show_only_three_tracking_words(self):
        make_complaint(self.student, category=Category.OTHER, title="Notice board fallen")
        make_complaint(self.student, title="Sparks from socket", description="Sparks fly from the socket.")
        late = make_complaint(self.student, title="Late complaint")
        Complaint.objects.filter(pk=late.pk).update(deadline=timezone.now() - timedelta(hours=1))
        self.login(self.admin)
        for url in [reverse("admin_dashboard"), reverse("admin_complaint_list")]:
            response = self.client.get(url)
            for word in [">Assigned<", ">Submitted<", ">Overdue<", ">Urgent<", "Safety review", "Unassigned"]:
                self.assertNotContains(response, word, msg_prefix=url)


# ---------------------------------------------------------------------------
# 11. Reopening requests
# ---------------------------------------------------------------------------
class ReopenTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.complaint = make_complaint(self.student, worker=self.electrician)
        services.change_status(self.complaint, Status.RESOLVED, self.electrician, "Fixed")

    def test_reporter_can_request_reopening(self):
        self.login(self.student)
        self.client.post(reverse("request_reopen", args=[self.complaint.pk]), {"reason": "Fan still does not work."})
        reopen_request = ReopenRequest.objects.get()
        self.assertEqual(reopen_request.status, ReopenRequest.RequestStatus.PENDING)
        self.complaint.refresh_from_db()
        # The complaint is NOT reopened automatically; the admin reviews first.
        self.assertEqual(self.complaint.status, Status.RESOLVED)

    def test_duplicate_pending_request_is_blocked(self):
        services.create_reopen_request(self.complaint, self.student, "Still broken today.")
        with self.assertRaises(services.InvalidTransition):
            services.create_reopen_request(self.complaint, self.student, "Still broken again.")

    def test_other_user_cannot_request_reopening(self):
        self.login(self.other_student)
        response = self.client.post(reverse("request_reopen", args=[self.complaint.pk]), {"reason": "Not my complaint"})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(ReopenRequest.objects.count(), 0)

    def test_cannot_reopen_unresolved_complaint(self):
        open_complaint = make_complaint(self.student, title="Another fan")
        with self.assertRaises(services.InvalidTransition):
            services.create_reopen_request(open_complaint, self.student, "Please reopen it now.")

    def test_admin_approval_reopens_complaint(self):
        reopen_request = services.create_reopen_request(self.complaint, self.student, "Fan still does not work.")
        self.login(self.admin)
        self.client.post(
            reverse("admin_review_reopen", args=[reopen_request.pk]), {"decision": "approve", "admin_note": "Checked"}
        )
        self.complaint.refresh_from_db()
        reopen_request.refresh_from_db()
        self.assertEqual(self.complaint.status, Status.REOPENED)
        self.assertEqual(self.complaint.reopen_count, 1)
        self.assertIsNone(self.complaint.resolved_at)
        self.assertGreater(self.complaint.deadline, timezone.now())
        self.assertEqual(reopen_request.status, ReopenRequest.RequestStatus.APPROVED)

    def test_admin_rejection_keeps_resolved(self):
        reopen_request = services.create_reopen_request(self.complaint, self.student, "Fan still does not work.")
        self.login(self.admin)
        self.client.post(reverse("admin_review_reopen", args=[reopen_request.pk]), {"decision": "reject"})
        self.complaint.refresh_from_db()
        self.assertEqual(self.complaint.status, Status.RESOLVED)

    def test_pending_request_is_marked_on_dashboard(self):
        services.create_reopen_request(self.complaint, self.student, "Fan still does not work.")
        self.login(self.admin)
        response = self.client.get(reverse("admin_dashboard"))
        self.assertIn(self.complaint, response.context["closed"])
        self.assertEqual(response.context["pending_request_ids"], {self.complaint.pk})
        self.assertContains(response, "Reopen requested")

    def test_reporter_can_confirm_and_close(self):
        self.login(self.student)
        self.client.post(reverse("confirm_resolution", args=[self.complaint.pk]))
        self.complaint.refresh_from_db()
        self.assertEqual(self.complaint.status, Status.CLOSED)
