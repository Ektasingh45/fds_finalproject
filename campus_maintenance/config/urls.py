"""Main URL configuration: sends each URL prefix to the right app."""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    # Django's built-in admin site (optional, for superusers)
    path("django-admin/", admin.site.urls),
    path("", include("accounts.urls")),
    path("complaints/", include("complaints.urls")),
    path("analytics/", include("analytics_app.urls")),
]

# Note: uploaded media files are NOT served publicly. See
# complaints.views.complaint_photo, which checks permissions first.
