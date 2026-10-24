"""
Role helpers used by every app.

All permission checks happen here on the server. Hiding a button in a
template is only for convenience; these checks are what actually protect
the data.
"""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from .models import Profile

ROLE_STUDENT = Profile.Role.STUDENT
ROLE_FACULTY = Profile.Role.FACULTY
ROLE_STAFF = Profile.Role.STAFF
ROLE_ADMIN = Profile.Role.ADMIN

# Students and faculty are both "reporters": they submit complaints.
REPORTER_ROLES = [ROLE_STUDENT, ROLE_FACULTY]


def get_role(user):
    """Return the role string of a user, or None if they have no role."""
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        return ROLE_ADMIN
    try:
        return user.profile.role
    except Profile.DoesNotExist:
        return None


def is_reporter(user):
    return get_role(user) in REPORTER_ROLES


def is_maintenance_staff(user):
    return get_role(user) == ROLE_STAFF


def is_admin(user):
    return get_role(user) == ROLE_ADMIN


def role_required(*allowed_roles):
    """
    Decorator for views. The user must be logged in AND have one of the
    allowed roles, otherwise Django returns "403 Forbidden".

    Example:
        @role_required(ROLE_ADMIN)
        def admin_dashboard(request): ...
    """

    def decorator(view_function):
        @wraps(view_function)
        @login_required
        def wrapper(request, *args, **kwargs):
            if get_role(request.user) not in allowed_roles:
                raise PermissionDenied("You do not have permission to open this page.")
            return view_function(request, *args, **kwargs)

        return wrapper

    return decorator
