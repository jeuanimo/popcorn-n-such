from __future__ import annotations

from datetime import timedelta

from django import forms
from django.utils import timezone


class DateRangeForm(forms.Form):
    start = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    end = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))

    def cleaned_range(self):
        if not self.is_valid():
            today = timezone.localdate()
            return today - timedelta(days=30), today
        start = self.cleaned_data.get("start")
        end = self.cleaned_data.get("end")
        today = timezone.localdate()
        if not end:
            end = today
        if not start:
            start = end - timedelta(days=30)
        if start > end:
            start, end = end, start
        return start, end

