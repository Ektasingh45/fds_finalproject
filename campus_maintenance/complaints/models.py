import os
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone


# ---------------------------------------------------------------------------
# Choice lists shared by several models
# ---------------------------------------------------------------------------
class Category(models.TextChoices):
    ELECTRICAL = "electrical", "Electrical"
    PLUMBING = "plumbing", "Plumbing"
    WATER_SUPPLY = "water_supply", "Water Supply"
    FURNITURE = "furniture", "Furniture / Carpentry"
    CLEANING = "cleaning", "Cleaning / Housekeeping"
    NETWORK = "network", "Network / Wi-Fi"
    EQUIPMENT = "equipment", "Lab / IT Equipment"
    CIVIL = "civil", "Building / Civil Work"
    OTHER = "other", "Other"


class Priority(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"
    URGENT = "urgent", "Urgent"


class Status(models.TextChoices):
    SUBMITTED = "submitted", "Submitted"
    ASSIGNED = "assigned", "Assigned"
    IN_PROGRESS = "in_progress", "In Progress"
    RESOLVED = "resolved", "Resolved"
    REOPENED = "reopened", "Reopened"
    CLOSED = "closed", "Closed"


# Work is finished in these statuses, so they can never be "overdue".
COMPLETED_STATUSES = [Status.RESOLVED, Status.CLOSED]

# The administrator tracks complaints with only three words:
#   Open        = submitted, no worker yet
#   In Progress = a worker has been assigned (assigning is what starts the work)
#   Closed      = work finished
TRACKING_OPEN = "open"
TRACKING_IN_PROGRESS = "in_progress"
TRACKING_CLOSED = "closed"
TRACKING_GROUPS = {
    TRACKING_OPEN: [Status.SUBMITTED],
    TRACKING_IN_PROGRESS: [Status.ASSIGNED, Status.IN_PROGRESS, Status.REOPENED],
    TRACKING_CLOSED: [Status.RESOLVED, Status.CLOSED],
}
TRACKING_LABELS = {
    TRACKING_OPEN: "Open",
    TRACKING_IN_PROGRESS: "In Progress",
    TRACKING_CLOSED: "Closed",
}


# The administrator also sees only three priority levels: Low, Medium, High.
# "Urgent" (set by the safety rules) is shown to the administrator as High.
ADMIN_PRIORITY_LEVELS = {
    "low": [Priority.LOW],
    "medium": [Priority.MEDIUM],
    "high": [Priority.HIGH, Priority.URGENT],
}
ADMIN_PRIORITY_LABELS = {"low": "Low", "medium": "Medium", "high": "High"}


def admin_priority(priority):
    """Return 'low', 'medium' or 'high' for a priority value."""
    for level, priorities in ADMIN_PRIORITY_LEVELS.items():
        if priority in priorities:
            return level
    return ""


def tracking_group(status):
    """Return 'open', 'in_progress' or 'closed' for a detailed status."""
    for group, statuses in TRACKING_GROUPS.items():
        if status in statuses:
            return group
    return ""


# ---------------------------------------------------------------------------
# Upload helpers
# ---------------------------------------------------------------------------
ALLOWED_PHOTO_EXTENSIONS = ["jpg", "jpeg", "png"]


def validate_photo_size(uploaded_file):
    max_bytes = settings.MAX_PHOTO_SIZE_MB * 1024 * 1024
    if uploaded_file.size > max_bytes:
        raise ValidationError(f"The photo must be smaller than {settings.MAX_PHOTO_SIZE_MB} MB.")


def complaint_photo_path(instance, filename):
    """Save photos with a random name so original file names are never exposed."""
    extension = os.path.splitext(filename)[1].lower()
    return f"complaint_photos/{uuid.uuid4().hex}{extension}"


def resolution_photo_path(instance, filename):
    extension = os.path.splitext(filename)[1].lower()
    return f"resolution_photos/{uuid.uuid4().hex}{extension}"


PHOTO_VALIDATORS = [FileExtensionValidator(ALLOWED_PHOTO_EXTENSIONS), validate_photo_size]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class Complaint(models.Model):
    """One maintenance complaint submitted by a student or faculty member."""

    # Example: CMP-2026-00042. Filled in automatically after the first save.
    reference_id = models.CharField(max_length=20, unique=True, null=True, blank=True, editable=False)
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="complaints"
    )
    title = models.CharField(max_length=150)
    description = models.TextField()
    category = models.CharField(max_length=20, choices=Category.choices)
    building = models.CharField(max_length=100)
    floor = models.CharField(max_length=20)
    room = models.CharField(max_length=50, help_text="Room number or area, e.g. 204, Corridor, Washroom near Lab 3")

    # What the reporter selected, kept for reference.
    reported_urgency = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    # The priority actually used, calculated by the rules in services.py.
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    # True when the complaint may be a safety hazard and a human should check it.
    safety_review_needed = models.BooleanField(default=False)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SUBMITTED)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_complaints",
    )

    submitted_at = models.DateTimeField(default=timezone.now)
    deadline = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_notes = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    reopen_count = models.PositiveIntegerField(default=0)

    photo = models.ImageField(
        upload_to=complaint_photo_path, blank=True, validators=PHOTO_VALIDATORS
    )
    resolution_photo = models.ImageField(
        upload_to=resolution_photo_path, blank=True, validators=PHOTO_VALIDATORS
    )

    class Meta:
        ordering = ["-submitted_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["category"]),
            models.Index(fields=["deadline"]),
        ]
        constraints = [
            # A complaint cannot be resolved before it was submitted.
            models.CheckConstraint(
                condition=Q(resolved_at__isnull=True) | Q(resolved_at__gte=F("submitted_at")),
                name="resolved_after_submitted",
            ),
        ]

    def __str__(self):
        return f"{self.reference_id or 'New'} - {self.title}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # The database id only exists after the first save, so the
        # reference ID is created right after it. The id is unique,
        # so the reference ID is unique as well.
        if not self.reference_id:
            year = self.submitted_at.year
            self.reference_id = f"CMP-{year}-{self.pk:05d}"
            super().save(update_fields=["reference_id"])

    @property
    def location(self):
        return f"{self.building}, Floor {self.floor}, {self.room}"

    @property
    def is_completed(self):
        return self.status in COMPLETED_STATUSES

    @property
    def tracking(self):
        return tracking_group(self.status)

    @property
    def tracking_label(self):
        return TRACKING_LABELS.get(self.tracking, "")

    @property
    def admin_priority(self):
        return admin_priority(self.priority)

    @property
    def admin_priority_label(self):
        return ADMIN_PRIORITY_LABELS.get(self.admin_priority, "")

    @property
    def is_overdue(self):
        """Overdue = deadline has passed and the work is not finished."""
        if self.deadline is None or self.is_completed:
            return False
        return timezone.now() > self.deadline


class ComplaintStatusHistory(models.Model):
    """One row for every status change or work note on a complaint."""

    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name="history")
    old_status = models.CharField(max_length=20, choices=Status.choices, blank=True)
    new_status = models.CharField(max_length=20, choices=Status.choices)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at", "id"]
        verbose_name_plural = "complaint status history"

    def __str__(self):
        return f"{self.complaint.reference_id}: {self.old_status or '-'} -> {self.new_status}"

    @property
    def changed_by_name(self):
        if self.changed_by is None:
            return "System (automatic rule)"
        return self.changed_by.get_full_name() or self.changed_by.username


class PriorityDeadline(models.Model):
    """Configurable target resolution time for each priority (example values only)."""

    priority = models.CharField(max_length=10, choices=Priority.choices, unique=True)
    target_hours = models.PositiveIntegerField(validators=[MinValueValidator(1), MaxValueValidator(720)])

    def __str__(self):
        return f"{self.get_priority_display()}: {self.target_hours} hours"


class ReopenRequest(models.Model):
    """A reporter says a 'resolved' complaint is not actually fixed. The admin reviews it."""

    class RequestStatus(models.TextChoices):
        PENDING = "pending", "Pending review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name="reopen_requests")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reopen_requests"
    )
    reason = models.TextField()
    status = models.CharField(max_length=10, choices=RequestStatus.choices, default=RequestStatus.PENDING)
    admin_note = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_reopen_requests",
    )
    created_at = models.DateTimeField(default=timezone.now)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # Only one pending request per complaint at a time.
            models.UniqueConstraint(
                fields=["complaint"],
                condition=Q(status="pending"),
                name="one_pending_reopen_per_complaint",
            ),
        ]

    def __str__(self):
        return f"Reopen request for {self.complaint.reference_id} ({self.status})"
