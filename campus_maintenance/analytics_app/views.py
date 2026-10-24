import csv

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from accounts.permissions import ROLE_ADMIN, role_required
from complaints.forms import ComplaintFilterForm
from complaints.models import Complaint
from complaints.views import apply_filters

from .analysis import CSVValidationError, build_report, load_historical_csv, records_to_dataframe
from .forms import HistoricalCSVForm


def local_naive(value):
    """Convert a timezone-aware datetime to local time without timezone (Pandas-friendly)."""
    if value is None:
        return None
    return timezone.localtime(value).replace(tzinfo=None)


def complaints_dataframe():
    """Load live complaints from the database into a Pandas DataFrame."""
    rows = Complaint.objects.values(
        "reference_id", "category", "building", "floor", "room",
        "priority", "status", "submitted_at", "resolved_at", "deadline",
    )
    records = []
    for row in rows:
        row["submitted_at"] = local_naive(row["submitted_at"])
        row["resolved_at"] = local_naive(row["resolved_at"])
        row["deadline"] = local_naive(row["deadline"])
        records.append(row)
    return records_to_dataframe(records)


@role_required(ROLE_ADMIN)
def analytics_dashboard(request):
    now = local_naive(timezone.now())
    report = build_report(complaints_dataframe(), now)
    return render(request, "analytics_app/dashboard.html", {"report": report})


def safe_csv_value(value):
    """
    Stop 'CSV injection': spreadsheet programs treat cells starting with
    = + - @ as formulas, so we put an apostrophe in front of them.
    """
    text = "" if value is None else str(value)
    if text and text[0] in ("=", "+", "-", "@"):
        return "'" + text
    return text


@role_required(ROLE_ADMIN)
def export_csv(request):
    """Download complaints (optionally filtered) as a CSV file."""
    filter_form = ComplaintFilterForm(request.GET or None)
    complaints = apply_filters(Complaint.objects.select_related("reporter", "assigned_to"), filter_form)

    response = HttpResponse(content_type="text/csv")
    filename = f"complaints_{timezone.localdate():%Y%m%d}.csv"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)
    writer.writerow([
        "complaint_id", "title", "category", "building", "floor", "room", "priority",
        "status", "reporter", "assigned_to", "submitted_at", "deadline", "resolved_at",
        "overdue", "reopen_count",
    ])
    for complaint in complaints:
        assigned = complaint.assigned_to.username if complaint.assigned_to else ""
        writer.writerow([safe_csv_value(value) for value in [
            complaint.reference_id,
            complaint.title,
            complaint.category,
            complaint.building,
            complaint.floor,
            complaint.room,
            complaint.admin_priority_label,  # Low / Medium / High
            complaint.tracking_label,  # Open / In Progress / Closed
            complaint.reporter.username,
            assigned,
            f"{local_naive(complaint.submitted_at):%Y-%m-%d %H:%M}",
            f"{local_naive(complaint.deadline):%Y-%m-%d %H:%M}" if complaint.deadline else "",
            f"{local_naive(complaint.resolved_at):%Y-%m-%d %H:%M}" if complaint.resolved_at else "",
            "yes" if complaint.is_overdue else "no",
            complaint.reopen_count,
        ]])
    return response


@role_required(ROLE_ADMIN)
def historical_upload(request):
    """
    Analyse an uploaded historical CSV. The data is only used to build the
    report shown on the page; it is never saved into the live database.
    """
    report = None
    warnings = []
    error_message = None

    if request.method == "POST":
        form = HistoricalCSVForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                df, warnings = load_historical_csv(
                    form.cleaned_data["csv_file"],
                    max_bytes=settings.MAX_CSV_SIZE_MB * 1024 * 1024,
                    max_rows=settings.MAX_CSV_ROWS,
                )
                now = local_naive(timezone.now())
                report = build_report(df, now)
            except CSVValidationError as error:
                error_message = str(error)
    else:
        form = HistoricalCSVForm()

    context = {
        "form": form,
        "report": report,
        "warnings": warnings,
        "error_message": error_message,
        "required_columns": ["complaint_id", "category", "building", "priority", "status", "submitted_at"],
        "optional_columns": ["floor", "room", "resolved_at"],
    }
    status_code = 400 if error_message else 200
    return render(request, "analytics_app/historical_upload.html", context, status=status_code)
