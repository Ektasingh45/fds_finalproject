"""
Business rules of the complaint system, kept in one file so they are easy
to read, test and explain:

1. Priority rules        -> calculate_priority()
2. Deadline rules        -> calculate_deadline()
3. Submission           -> submit_complaint() (no automatic assignment)
4. Status transitions    -> ALLOWED_TRANSITIONS, change_status(), assign_complaint()
5. Overdue detection     -> overdue_filter()
6. Reopening requests    -> create_reopen_request(), review_reopen_request()
"""
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import (
    COMPLETED_STATUSES,
    Category,
    ComplaintStatusHistory,
    Priority,
    PriorityDeadline,
    ReopenRequest,
    Status,
)

# ---------------------------------------------------------------------------
# 1. Priority rules
# ---------------------------------------------------------------------------
# Words that may indicate a safety hazard. Matching one of them does NOT
# prove there is a hazard; it only makes the complaint Urgent and asks a
# human (the administrator) to review it.
SAFETY_KEYWORDS = [
    "fire",
    "smoke",
    "spark",
    "shock",
    "electrocut",
    "exposed wire",
    "live wire",
    "short circuit",
    "burning smell",
    "gas leak",
    "gas smell",
    "flood",
    "collapse",
    "ceiling crack",
    "falling",
]

# Some categories affect basic facilities, so they are never below Medium.
CATEGORY_MINIMUM_PRIORITY = {
    Category.ELECTRICAL: Priority.MEDIUM,
    Category.WATER_SUPPLY: Priority.MEDIUM,
    Category.PLUMBING: Priority.MEDIUM,
}

# Lowest to highest, used to compare priorities.
PRIORITY_ORDER = [Priority.LOW, Priority.MEDIUM, Priority.HIGH, Priority.URGENT]


def find_safety_keywords(text):
    """Return the list of safety keywords found in the text."""
    text = text.lower()
    found = []
    for keyword in SAFETY_KEYWORDS:
        if keyword in text:
            found.append(keyword)
    return found


def higher_priority(first, second):
    """Return whichever of the two priorities is more serious."""
    if PRIORITY_ORDER.index(first) >= PRIORITY_ORDER.index(second):
        return first
    return second


def calculate_priority(category, reported_urgency, title, description):
    """
    Apply the documented priority rules.

    Rule 1: Start with the urgency the reporter selected.
    Rule 2: Electrical, plumbing and water-supply complaints are at least Medium.
    Rule 3: If safety keywords appear in the title/description, the
            priority becomes Urgent.
    Rule 4: Every Urgent complaint is flagged for human safety review.

    Returns a tuple: (priority, safety_review_needed, list_of_reasons)
    """
    reasons = []
    if reported_urgency not in PRIORITY_ORDER:
        reported_urgency = Priority.MEDIUM
        reasons.append("Unknown urgency was replaced with Medium.")

    priority = reported_urgency
    reasons.append(f"Reporter selected {Priority(reported_urgency).label}.")

    minimum = CATEGORY_MINIMUM_PRIORITY.get(category)
    if minimum and higher_priority(minimum, priority) != priority:
        priority = minimum
        reasons.append(f"Category rule raised priority to {Priority(minimum).label}.")

    keywords = find_safety_keywords(f"{title} {description}")
    if keywords:
        priority = Priority.URGENT
        reasons.append("Possible safety words found: " + ", ".join(keywords) + ".")

    safety_review_needed = priority == Priority.URGENT
    if safety_review_needed:
        reasons.append("Marked for administrator safety review.")

    return priority, safety_review_needed, reasons


# ---------------------------------------------------------------------------
# 2. Deadline rules
# ---------------------------------------------------------------------------
# EXAMPLE demonstration values, not official college service guarantees.
# They are stored in the PriorityDeadline table (seed_demo fills it) and can
# be changed by a superuser in the Django admin site (/django-admin/).
DEFAULT_TARGET_HOURS = {
    Priority.URGENT: 4,
    Priority.HIGH: 24,
    Priority.MEDIUM: 72,
    Priority.LOW: 168,  # 7 days
}


def get_target_hours(priority):
    """Read the target hours from the database, or use the default value."""
    setting = PriorityDeadline.objects.filter(priority=priority).first()
    if setting:
        return setting.target_hours
    return DEFAULT_TARGET_HOURS[priority]


def calculate_deadline(priority, start_time):
    """Deadline = start time + target hours for the priority."""
    return start_time + timedelta(hours=get_target_hours(priority))


# ---------------------------------------------------------------------------
# 3. Submission
# ---------------------------------------------------------------------------
# There is no automatic assignment: every new complaint is Open until the
# administrator chooses a worker from the "Assign to" drop-down.
def record_history(complaint, old_status, new_status, user, note=""):
    """Write one row in the status history table."""
    return ComplaintStatusHistory.objects.create(
        complaint=complaint,
        old_status=old_status,
        new_status=new_status,
        changed_by=user,
        note=note,
    )


@transaction.atomic
def submit_complaint(complaint, reporter):
    """
    Save a new complaint, set its priority and deadline, and leave it Open
    for the administrator to assign. `complaint` is an unsaved Complaint
    built from the form.
    """
    complaint.reporter = reporter
    complaint.submitted_at = timezone.now()

    priority, review_needed, reasons = calculate_priority(
        complaint.category, complaint.reported_urgency, complaint.title, complaint.description
    )
    complaint.priority = priority
    complaint.safety_review_needed = review_needed
    complaint.deadline = calculate_deadline(priority, complaint.submitted_at)
    complaint.status = Status.SUBMITTED
    complaint.save()

    record_history(
        complaint, "", Status.SUBMITTED, reporter,
        "Complaint submitted. Priority rules: " + " ".join(reasons)
        + " Waiting for the administrator to assign a worker.",
    )
    return complaint


# ---------------------------------------------------------------------------
# 4. Status transitions
# ---------------------------------------------------------------------------
# Which new statuses are allowed from each current status.
ALLOWED_TRANSITIONS = {
    Status.SUBMITTED: [Status.ASSIGNED, Status.RESOLVED, Status.CLOSED],
    Status.ASSIGNED: [Status.IN_PROGRESS, Status.RESOLVED, Status.CLOSED],
    Status.IN_PROGRESS: [Status.RESOLVED, Status.CLOSED],
    Status.RESOLVED: [Status.CLOSED, Status.REOPENED, Status.SUBMITTED],
    Status.REOPENED: [Status.IN_PROGRESS, Status.RESOLVED, Status.CLOSED],
    Status.CLOSED: [],
}


class InvalidTransition(Exception):
    """Raised when a status change breaks the rules."""


def can_change_status(old_status, new_status):
    return new_status in ALLOWED_TRANSITIONS.get(old_status, [])


@transaction.atomic
def change_status(complaint, new_status, user, note="", resolution_photo=None):
    """Change the status after checking the rules, and record it in the history."""
    old_status = complaint.status
    if not can_change_status(old_status, new_status):
        raise InvalidTransition(
            f"A complaint cannot move from {Status(old_status).label} to {Status(new_status).label}."
        )
    if new_status == Status.RESOLVED and not note.strip():
        raise InvalidTransition("Resolution notes are required when marking a complaint Resolved.")

    now = timezone.now()
    complaint.status = new_status

    if new_status == Status.RESOLVED:
        complaint.resolved_at = now
        complaint.resolution_notes = note.strip()
        if resolution_photo:
            complaint.resolution_photo = resolution_photo
    elif old_status == Status.RESOLVED and new_status in (Status.REOPENED, Status.SUBMITTED):
        # Work restarts, so a fresh deadline is calculated from now.
        complaint.resolved_at = None
        complaint.reopen_count += 1
        complaint.deadline = calculate_deadline(complaint.priority, now)

    complaint.save()
    record_history(complaint, old_status, new_status, user, note.strip())
    return complaint


def add_work_note(complaint, user, note):
    """A note without a status change (for example 'waiting for spare part')."""
    return record_history(complaint, complaint.status, complaint.status, user, note.strip())


@transaction.atomic
def assign_complaint(complaint, staff_member, admin_user, note=""):
    """Administrator assigns or reassigns a complaint to a staff member."""
    if complaint.is_completed:
        raise InvalidTransition("Resolved or closed complaints cannot be reassigned.")

    old_status = complaint.status
    complaint.assigned_to = staff_member
    if old_status == Status.SUBMITTED:
        complaint.status = Status.ASSIGNED
    complaint.save()

    staff_name = staff_member.get_full_name() or staff_member.username
    message = f"Assigned to {staff_name} by administrator."
    if note.strip():
        message += " " + note.strip()
    record_history(complaint, old_status, complaint.status, admin_user, message)
    return complaint


# ---------------------------------------------------------------------------
# 5. Overdue filter (calculated every time a page loads)
# ---------------------------------------------------------------------------
def open_filter():
    """Complaints that still need work."""
    return ~Q(status__in=COMPLETED_STATUSES)


def overdue_filter(now=None):
    """Deadline passed AND work not finished."""
    if now is None:
        now = timezone.now()
    return Q(deadline__lt=now) & open_filter()


# ---------------------------------------------------------------------------
# 6. Reopening requests and reporter confirmation
# ---------------------------------------------------------------------------
def has_pending_reopen_request(complaint):
    return complaint.reopen_requests.filter(status=ReopenRequest.RequestStatus.PENDING).exists()


@transaction.atomic
def create_reopen_request(complaint, user, reason):
    if complaint.status != Status.RESOLVED:
        raise InvalidTransition("Only resolved complaints can be reopened.")
    if has_pending_reopen_request(complaint):
        raise InvalidTransition("A reopening request is already waiting for review.")

    reopen_request = ReopenRequest.objects.create(complaint=complaint, requested_by=user, reason=reason.strip())
    record_history(
        complaint, complaint.status, complaint.status, user,
        "Reporter requested reopening: " + reason.strip(),
    )
    return reopen_request


@transaction.atomic
def review_reopen_request(reopen_request, admin_user, approve, admin_note=""):
    if reopen_request.status != ReopenRequest.RequestStatus.PENDING:
        raise InvalidTransition("This request has already been reviewed.")

    reopen_request.reviewed_by = admin_user
    reopen_request.reviewed_at = timezone.now()
    reopen_request.admin_note = admin_note.strip()
    complaint = reopen_request.complaint

    if approve:
        reopen_request.status = ReopenRequest.RequestStatus.APPROVED
        reopen_request.save()
        # With a worker it goes back to In Progress; without one it goes back to Open.
        if complaint.assigned_to_id:
            new_status = Status.REOPENED
        else:
            new_status = Status.SUBMITTED
        change_status(complaint, new_status, admin_user, "Reopening approved. " + admin_note.strip())
    else:
        reopen_request.status = ReopenRequest.RequestStatus.REJECTED
        reopen_request.save()
        record_history(
            complaint, complaint.status, complaint.status, admin_user,
            "Reopening request rejected. " + admin_note.strip(),
        )
    return reopen_request


def confirm_resolution(complaint, user):
    """The reporter confirms the problem is fixed, which closes the complaint."""
    return change_status(complaint, Status.CLOSED, user, "Reporter confirmed the issue is fixed.")
