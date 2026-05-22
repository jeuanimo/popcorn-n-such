from __future__ import annotations

from django import forms

from notifications.models import StaffAlertEventType, StaffAlertPreference
from notifications.models import NotificationPreference, NotificationType


class StaffAlertPreferenceForm(forms.ModelForm):
    enabled_events = forms.MultipleChoiceField(
        required=False,
        choices=StaffAlertEventType.choices,
        widget=forms.CheckboxSelectMultiple,
        help_text="If none selected, all alerts are enabled.",
    )

    class Meta:
        model = StaffAlertPreference
        fields = [
            "enabled",
            "receive_internal",
            "receive_email",
            "receive_sms",
            "sms_opt_in",
            "enabled_events",
        ]


class NotificationPreferenceForm(forms.ModelForm):
    enabled_types = forms.MultipleChoiceField(
        required=False,
        choices=NotificationType.choices,
        widget=forms.CheckboxSelectMultiple,
        help_text="If none selected, all notifications are enabled.",
    )

    class Meta:
        model = NotificationPreference
        fields = [
            "enabled",
            "receive_in_app",
            "receive_email",
            "receive_sms",
            "sms_opt_in",
            "enabled_types",
        ]
