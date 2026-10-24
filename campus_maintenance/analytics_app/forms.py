from django import forms
from django.conf import settings


class HistoricalCSVForm(forms.Form):
    csv_file = forms.FileField(
        label="Historical complaint CSV",
        help_text=f"Only .csv files, maximum {settings.MAX_CSV_SIZE_MB} MB.",
    )
