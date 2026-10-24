from django.urls import path

from . import views

urlpatterns = [
    path("", views.analytics_dashboard, name="analytics_dashboard"),
    path("export/", views.export_csv, name="export_csv"),
    path("historical/", views.historical_upload, name="historical_upload"),
]
