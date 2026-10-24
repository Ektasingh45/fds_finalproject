from django.urls import path

from . import views

urlpatterns = [
    # Student / faculty
    path("my/", views.reporter_dashboard, name="reporter_dashboard"),
    path("new/", views.complaint_create, name="complaint_create"),
    path("<int:pk>/submitted/", views.complaint_submitted, name="complaint_submitted"),
    path("<int:pk>/reopen/", views.request_reopen, name="request_reopen"),
    path("<int:pk>/confirm/", views.confirm_resolution, name="confirm_resolution"),
    # Shared
    path("<int:pk>/", views.complaint_detail, name="complaint_detail"),
    path("<int:pk>/photo/<str:kind>/", views.complaint_photo, name="complaint_photo"),
    # Administrator
    path("admin/", views.admin_dashboard, name="admin_dashboard"),
    path("<int:pk>/progress/", views.admin_update_progress, name="admin_update_progress"),
    path("admin/all/", views.admin_complaint_list, name="admin_complaint_list"),
    path("<int:pk>/assign/", views.admin_assign, name="admin_assign"),
    path("reopen-requests/<int:request_id>/review/", views.admin_review_reopen, name="admin_review_reopen"),
]
