from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.permissions import REPORTER_ROLES, ROLE_ADMIN, get_role, role_required

from . import services
from .forms import (
    AdminAssignForm,
    ComplaintFilterForm,
    ComplaintForm,
    ProgressUpdateForm,
    ReopenRequestForm,
    ReopenReviewForm,
    active_staff_queryset,
)
from .models import (
    ADMIN_PRIORITY_LEVELS,
    COMPLETED_STATUSES,
    TRACKING_CLOSED,
    TRACKING_GROUPS,
    TRACKING_IN_PROGRESS,
    TRACKING_LABELS,
    TRACKING_OPEN,
    Complaint,
    ReopenRequest,
    Status,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_visible_complaint(request, pk):
    """
    Return the complaint only if the logged-in user may see it:
      - the reporter who submitted it,
      - any administrator.
    Everyone else gets "404 Not Found", so we do not even reveal that it exists.
    """
    complaint = get_object_or_404(Complaint.objects.select_related("reporter", "assigned_to"), pk=pk)
    role = get_role(request.user)
    if role == ROLE_ADMIN:
        return complaint
    if role in REPORTER_ROLES and complaint.reporter_id == request.user.id:
        return complaint
    raise Http404("Complaint not found.")


def apply_filters(complaints, form):
    """Filter a queryset using the values from ComplaintFilterForm."""
    if not form.is_valid():
        return complaints
    data = form.cleaned_data

    # Open / In Progress / Closed (the dashboard boxes link here).
    view = data.get("view")
    if view:
        complaints = complaints.filter(status__in=TRACKING_GROUPS[view])
    # Low / Medium / High ("High" also includes Urgent).
    if data.get("priority"):
        complaints = complaints.filter(priority__in=ADMIN_PRIORITY_LEVELS[data["priority"]])
    if data.get("search"):
        text = data["search"].strip()
        complaints = complaints.filter(
            Q(reference_id__icontains=text) | Q(title__icontains=text) | Q(building__icontains=text)
        )
    return complaints


def pending_request_ids():
    """Ids of complaints whose reporter has asked for reopening (shown as a badge)."""
    pending = ReopenRequest.objects.filter(status=ReopenRequest.RequestStatus.PENDING)
    return set(pending.values_list("complaint_id", flat=True))


def render_detail(request, complaint, **forms):
    """
    Show the complaint detail page. Each role sees different action forms.
    Views that receive an invalid POST pass their bound form in **forms
    so the error messages are displayed.
    """
    role = get_role(request.user)
    pending_request = complaint.reopen_requests.filter(status=ReopenRequest.RequestStatus.PENDING).first()
    context = {
        "complaint": complaint,
        "history": complaint.history.select_related("changed_by"),
        "reopen_requests": complaint.reopen_requests.select_related("requested_by", "reviewed_by"),
        "pending_request": pending_request,
    }

    if role in REPORTER_ROLES and complaint.reporter_id == request.user.id:
        if complaint.status == Status.RESOLVED and pending_request is None:
            context["reopen_form"] = forms.get("reopen_form") or ReopenRequestForm()
            context["can_confirm"] = True

    if role == ROLE_ADMIN:
        # Open -> Assign (makes it In Progress). Open or In Progress -> Close.
        if not complaint.is_completed:
            initial_staff = {"staff": complaint.assigned_to_id} if complaint.assigned_to_id else {}
            context["assign_form"] = forms.get("assign_form") or AdminAssignForm(initial=initial_staff)
        if not complaint.is_completed:
            context["progress_form"] = forms.get("progress_form") or ProgressUpdateForm(
                initial={"action": ProgressUpdateForm.ACTION_CLOSE}
            )
        if pending_request:
            context["review_form"] = forms.get("review_form") or ReopenReviewForm()

    return render(request, "complaints/complaint_detail.html", context)


# ---------------------------------------------------------------------------
# Student / faculty views
# ---------------------------------------------------------------------------
@role_required(*REPORTER_ROLES)
def reporter_dashboard(request):
    complaints = Complaint.objects.filter(reporter=request.user).select_related("assigned_to")
    context = {
        "complaints": complaints,
        "total_count": complaints.count(),
        "open_count": complaints.exclude(status__in=COMPLETED_STATUSES).count(),
        "resolved_count": complaints.filter(status__in=COMPLETED_STATUSES).count(),
    }
    return render(request, "complaints/reporter_dashboard.html", context)


@role_required(*REPORTER_ROLES)
def complaint_create(request):
    if request.method == "POST":
        form = ComplaintForm(request.POST, request.FILES)
        if form.is_valid():
            complaint = form.save(commit=False)
            services.submit_complaint(complaint, request.user)
            messages.success(request, f"Complaint {complaint.reference_id} was submitted.")
            return redirect("complaint_submitted", pk=complaint.pk)
        messages.error(request, "Please correct the errors below.")
    else:
        form = ComplaintForm()
    return render(request, "complaints/complaint_form.html", {"form": form})


@role_required(*REPORTER_ROLES)
def complaint_submitted(request, pk):
    complaint = get_object_or_404(Complaint, pk=pk, reporter=request.user)
    return render(request, "complaints/complaint_submitted.html", {"complaint": complaint})


@role_required(*REPORTER_ROLES)
@require_POST
def request_reopen(request, pk):
    complaint = get_object_or_404(Complaint, pk=pk, reporter=request.user)
    form = ReopenRequestForm(request.POST)
    if not form.is_valid():
        return render_detail(request, complaint, reopen_form=form)
    try:
        services.create_reopen_request(complaint, request.user, form.cleaned_data["reason"])
        messages.success(request, "Your reopening request was sent to the administrator for review.")
    except services.InvalidTransition as error:
        messages.error(request, str(error))
    return redirect("complaint_detail", pk=complaint.pk)


@role_required(*REPORTER_ROLES)
@require_POST
def confirm_resolution(request, pk):
    complaint = get_object_or_404(Complaint, pk=pk, reporter=request.user)
    if complaint.status != Status.RESOLVED:
        messages.error(request, "Only resolved complaints can be confirmed.")
    elif services.has_pending_reopen_request(complaint):
        messages.error(request, "A reopening request is waiting for review.")
    else:
        services.confirm_resolution(complaint, request.user)
        messages.success(request, "Thank you. The complaint is now closed.")
    return redirect("complaint_detail", pk=complaint.pk)


# ---------------------------------------------------------------------------
# Shared views (permission checked inside get_visible_complaint)
# ---------------------------------------------------------------------------
@login_required
def complaint_detail(request, pk):
    complaint = get_visible_complaint(request, pk)
    return render_detail(request, complaint)


@login_required
def complaint_photo(request, pk, kind):
    """
    Serve an uploaded photo only to users who may see the complaint.
    Photos are never available through a public URL.
    """
    complaint = get_visible_complaint(request, pk)
    if kind == "issue":
        photo = complaint.photo
    elif kind == "resolution":
        photo = complaint.resolution_photo
    else:
        raise Http404("Unknown photo type.")
    if not photo:
        raise Http404("No photo uploaded.")
    try:
        return FileResponse(photo.open("rb"))
    except FileNotFoundError:
        raise Http404("Photo file is missing.")


# ---------------------------------------------------------------------------
# Administrator views
# ---------------------------------------------------------------------------
@role_required(ROLE_ADMIN)
@require_POST
def admin_update_progress(request, pk):
    """The administrator adds a work note or closes an Open / In Progress complaint."""
    complaint = get_object_or_404(Complaint, pk=pk)
    form = ProgressUpdateForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, "Please correct the errors in the update form.")
        return render_detail(request, complaint, progress_form=form)

    note = form.cleaned_data["note"]
    try:
        if form.cleaned_data["action"] == ProgressUpdateForm.ACTION_CLOSE:
            # Internally "Resolved": the reporter can still confirm it or ask to reopen.
            services.change_status(
                complaint, Status.RESOLVED, request.user, note,
                resolution_photo=form.cleaned_data.get("resolution_photo"),
            )
            messages.success(request, f"{complaint.reference_id} is now Closed.")
        else:
            services.add_work_note(complaint, request.user, note)
            messages.success(request, "Work note added.")
    except services.InvalidTransition as error:
        messages.error(request, str(error))
    return redirect("complaint_detail", pk=complaint.pk)


@role_required(ROLE_ADMIN)
def admin_dashboard(request):
    """Three boxes and three lists: Open, In Progress, Closed."""
    complaints = Complaint.objects.select_related("reporter", "assigned_to")
    # Every list is arranged by date, newest complaint first.
    open_complaints = complaints.filter(status__in=TRACKING_GROUPS[TRACKING_OPEN]).order_by("-submitted_at")
    in_progress = complaints.filter(status__in=TRACKING_GROUPS[TRACKING_IN_PROGRESS]).order_by("-submitted_at")
    closed = complaints.filter(status__in=TRACKING_GROUPS[TRACKING_CLOSED]).order_by("-submitted_at")

    context = {
        "open_complaints": open_complaints,
        "in_progress": in_progress,
        "closed": closed,
        "open_count": open_complaints.count(),
        "in_progress_count": in_progress.count(),
        "closed_count": closed.count(),
        # Closed complaints the reporter says are not fixed
        "pending_request_ids": pending_request_ids(),
        # Workers offered in the "Assign to" drop-downs
        "assignable_staff": active_staff_queryset().select_related("profile"),
    }
    return render(request, "complaints/admin_dashboard.html", context)


@role_required(ROLE_ADMIN)
def admin_complaint_list(request):
    filter_form = ComplaintFilterForm(request.GET or None)
    complaints = apply_filters(Complaint.objects.select_related("reporter", "assigned_to"), filter_form)
    complaints = complaints.order_by("-submitted_at")  # newest first

    page_title = "All complaints"
    if filter_form.is_valid() and filter_form.cleaned_data.get("view"):
        page_title = TRACKING_LABELS[filter_form.cleaned_data["view"]] + " complaints"

    context = {
        "filter_form": filter_form,
        "complaints": complaints,
        "page_title": page_title,
        "pending_request_ids": pending_request_ids(),
    }
    return render(request, "complaints/admin_complaint_list.html", context)


@role_required(ROLE_ADMIN)
@require_POST
def admin_assign(request, pk):
    complaint = get_object_or_404(Complaint, pk=pk)
    form = AdminAssignForm(request.POST)
    if not form.is_valid():
        return render_detail(request, complaint, assign_form=form)
    staff_member = form.cleaned_data["staff"]
    try:
        services.assign_complaint(complaint, staff_member, request.user, form.cleaned_data["note"])
        messages.success(
            request,
            f"{complaint.reference_id} assigned to {staff_member.get_full_name() or staff_member.username}.",
        )
    except services.InvalidTransition as error:
        messages.error(request, str(error))
    # The quick-assign form on the dashboard sends us back there.
    if request.POST.get("return_to") == "dashboard":
        return redirect("admin_dashboard")
    return redirect("complaint_detail", pk=complaint.pk)


@role_required(ROLE_ADMIN)
@require_POST
def admin_review_reopen(request, request_id):
    reopen_request = get_object_or_404(ReopenRequest, pk=request_id)
    complaint = reopen_request.complaint
    form = ReopenReviewForm(request.POST)
    if not form.is_valid():
        return render_detail(request, complaint, review_form=form)
    approve = form.cleaned_data["decision"] == "approve"
    try:
        services.review_reopen_request(reopen_request, request.user, approve, form.cleaned_data["admin_note"])
        if approve:
            messages.success(request, "Complaint reopened and sent back to the assigned worker (In Progress).")
        else:
            messages.info(request, "Reopening request rejected.")
    except services.InvalidTransition as error:
        messages.error(request, str(error))
    return redirect("complaint_detail", pk=complaint.pk)
