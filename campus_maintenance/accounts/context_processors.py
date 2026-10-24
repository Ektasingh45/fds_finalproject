from .permissions import REPORTER_ROLES, ROLE_ADMIN, ROLE_STAFF, get_role


def user_role(request):
    """Make the current user's role available in every template."""
    role = None
    if hasattr(request, "user"):
        role = get_role(request.user)
    return {
        "user_role": role,
        "is_reporter": role in REPORTER_ROLES,
        "is_maintenance_staff": role == ROLE_STAFF,
        "is_admin_user": role == ROLE_ADMIN,
    }
