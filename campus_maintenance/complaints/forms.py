import re

from django import forms
from django.contrib.auth.models import User

from .models import (
    ADMIN_PRIORITY_LABELS,
    PHOTO_VALIDATORS,
    TRACKING_CLOSED,
    TRACKING_IN_PROGRESS,
    TRACKING_OPEN,
    Complaint,
    ReopenRequest,
)


def clean_spaces(text):
    """Remove extra spaces: '  Main   Block ' -> 'Main Block'."""
    return re.sub(r"\s+", " ", text).strip()


def active_staff_queryset():
    return User.objects.filter(profile__role="staff", is_active=True).order_by("username")


class StaffChoiceField(forms.ModelChoiceField):
    """Shows staff as 'Full Name (Team)' in drop-downs."""

    def label_from_instance(self, user):
        name = user.get_full_name() or user.username
        team = getattr(getattr(user, "profile", None), "department", "")
        if team:
            return f"{name} ({team})"
        return name


class ComplaintForm(forms.ModelForm):
    """Form used by students/faculty to submit a complaint."""

    class Meta:
        model = Complaint
        fields = ["title", "description", "category", "building", "floor", "room", "reported_urgency", "photo"]
        labels = {
            "reported_urgency": "How urgent is it?",
            "photo": "Photo of the issue (optional)",
            "room": "Room or area",
        }
        help_texts = {
            "reported_urgency": "Low: minor issue. Medium: needs attention. "
            "High: stops normal use of the room. Urgent: possible safety danger.",
            "photo": "JPG or PNG, maximum 2 MB.",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 5}),
            "title": forms.TextInput(attrs={"placeholder": "e.g. Ceiling fan not working"}),
            "building": forms.TextInput(attrs={"placeholder": "e.g. Main Block"}),
            "floor": forms.TextInput(attrs={"placeholder": "e.g. 2 or Ground"}),
            "room": forms.TextInput(attrs={"placeholder": "e.g. 204 or Corridor"}),
        }

    def clean_title(self):
        title = clean_spaces(self.cleaned_data["title"])
        if len(title) < 5:
            raise forms.ValidationError("Please enter a title of at least 5 characters.")
        return title

    def clean_description(self):
        description = self.cleaned_data["description"].strip()
        if len(description) < 10:
            raise forms.ValidationError("Please describe the problem in at least 10 characters.")
        return description

    def clean_building(self):
        return clean_spaces(self.cleaned_data["building"]).title()

    def clean_floor(self):
        return clean_spaces(self.cleaned_data["floor"])

    def clean_room(self):
        return clean_spaces(self.cleaned_data["room"])


class ProgressUpdateForm(forms.Form):
    """
    Used by the administrator on an Open or In Progress complaint: either add
    a work note, or close the complaint.
    """

    ACTION_NOTE = ""
    ACTION_CLOSE = "close"
    ACTION_CHOICES = [
        (ACTION_NOTE, "Add a work note only"),
        (ACTION_CLOSE, "Close complaint"),
    ]

    action = forms.ChoiceField(choices=ACTION_CHOICES, label="Action", required=False)
    note = forms.CharField(
        label="Note (what was done, or why it is closed)",
        widget=forms.Textarea(attrs={"rows": 3}),
        required=False,
        max_length=2000,
    )
    resolution_photo = forms.ImageField(
        label="Completion photo (optional)",
        required=False,
        validators=PHOTO_VALIDATORS,
        help_text="JPG or PNG, maximum 2 MB.",
    )

    def clean(self):
        cleaned_data = super().clean()
        action = cleaned_data.get("action")
        note = (cleaned_data.get("note") or "").strip()
        if action == self.ACTION_CLOSE and not note:
            self.add_error("note", "Please write what was done, or why it is being closed.")
        elif action == self.ACTION_NOTE and not note:
            self.add_error("note", "Write a work note, or choose Close.")
        if cleaned_data.get("resolution_photo") and action != self.ACTION_CLOSE:
            self.add_error("resolution_photo", "A completion photo can only be added when closing.")
        return cleaned_data


class ReopenRequestForm(forms.ModelForm):
    class Meta:
        model = ReopenRequest
        fields = ["reason"]
        labels = {"reason": "Why is the problem not fixed?"}
        widgets = {"reason": forms.Textarea(attrs={"rows": 3})}

    def clean_reason(self):
        reason = self.cleaned_data["reason"].strip()
        if len(reason) < 10:
            raise forms.ValidationError("Please explain in at least 10 characters.")
        return reason


class AdminAssignForm(forms.Form):
    staff = StaffChoiceField(queryset=User.objects.none(), label="Assign to", empty_label="Select a worker")
    note = forms.CharField(required=False, max_length=500, label="Note (optional)")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["staff"].queryset = active_staff_queryset()


class ReopenReviewForm(forms.Form):
    DECISION_CHOICES = [("approve", "Approve and reopen"), ("reject", "Reject request")]
    decision = forms.ChoiceField(choices=DECISION_CHOICES, widget=forms.RadioSelect)
    admin_note = forms.CharField(max_length=500, required=False, label="Note to reporter")


class ComplaintFilterForm(forms.Form):
    """Filter for the administrator's complaint list. Submitted with GET, no JavaScript."""

    VIEW_CHOICES = [
        ("", "All complaints"),
        (TRACKING_OPEN, "Open"),
        (TRACKING_IN_PROGRESS, "In Progress"),
        (TRACKING_CLOSED, "Closed"),
    ]

    PRIORITY_CHOICES = [("", "All priorities")] + list(ADMIN_PRIORITY_LABELS.items())

    view = forms.ChoiceField(choices=VIEW_CHOICES, required=False, label="Status")
    priority = forms.ChoiceField(choices=PRIORITY_CHOICES, required=False, label="Priority")
    search = forms.CharField(required=False, max_length=100, label="Search ID / title / building")
