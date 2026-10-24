from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.shortcuts import redirect, render

from .forms import RegistrationForm, RoleLoginForm
from .permissions import REPORTER_ROLES, ROLE_ADMIN, get_role


class RoleLoginView(auth_views.LoginView):
    """Django's login view with our "Login as" form."""

    template_name = "accounts/login.html"
    authentication_form = RoleLoginForm
    redirect_authenticated_user = True


def home(request):
    """Send each logged-in user to the dashboard for their role."""
    role = get_role(request.user)
    if role in REPORTER_ROLES:
        return redirect("reporter_dashboard")
    if role == ROLE_ADMIN:
        return redirect("admin_dashboard")
    if request.user.is_authenticated:
        messages.warning(request, "Your account has no role yet. Please contact the administrator.")
    return render(request, "home.html")


def register(request):
    if request.user.is_authenticated:
        return redirect("home")

    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, "Your account was created. You can now submit complaints.")
            return redirect("home")
    else:
        form = RegistrationForm()
    return render(request, "accounts/register.html", {"form": form})
