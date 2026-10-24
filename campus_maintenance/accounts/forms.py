from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User

from .models import Profile
from .permissions import REPORTER_ROLES, ROLE_ADMIN, ROLE_STAFF, get_role


class RoleLoginForm(AuthenticationForm):
    """
    Login form with a "Login as" drop-down. The chosen option must match
    the account's real role, which is checked on the server.
    Maintenance workers do not log in; the administrator updates their work.
    """

    LOGIN_AS_REPORTER = "reporter"
    LOGIN_AS_ADMIN = "admin"
    LOGIN_AS_CHOICES = [
        (LOGIN_AS_REPORTER, "Student / Faculty"),
        (LOGIN_AS_ADMIN, "Administrator"),
    ]

    login_as = forms.ChoiceField(choices=LOGIN_AS_CHOICES, label="Login as")

    field_order = ["login_as", "username", "password"]

    def clean(self):
        # The parent class checks the username and password first.
        cleaned_data = super().clean()
        user = self.get_user()
        if user is None:
            return cleaned_data

        role = get_role(user)
        login_as = cleaned_data.get("login_as")
        if role == ROLE_STAFF:
            raise forms.ValidationError(
                "Maintenance worker accounts cannot log in. The administrator updates complaint progress."
            )
        if login_as == self.LOGIN_AS_ADMIN and role != ROLE_ADMIN:
            raise forms.ValidationError("This is not an administrator account. Choose 'Student / Faculty'.")
        if login_as == self.LOGIN_AS_REPORTER and role not in REPORTER_ROLES:
            raise forms.ValidationError("This is an administrator account. Choose 'Administrator' in 'Login as'.")
        return cleaned_data


class RegistrationForm(UserCreationForm):
    """Sign-up form for students and faculty. Administrators are created with createsuperuser."""

    # Only reporter roles can be chosen here, so nobody can register as admin.
    ROLE_CHOICES = [
        (Profile.Role.STUDENT, "Student"),
        (Profile.Role.FACULTY, "Faculty"),
    ]

    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField()
    role = forms.ChoiceField(choices=ROLE_CHOICES, label="I am a")
    department = forms.CharField(max_length=100, required=False, help_text="For example: CSE, Mechanical")

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email"]

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
            Profile.objects.create(
                user=user,
                role=self.cleaned_data["role"],
                department=self.cleaned_data["department"],
            )
        return user
