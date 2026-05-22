from __future__ import annotations

from django.urls import path

from .views import (
    DraftLabelPrintView,
    LabelCreateView,
    LabelDownloadView,
    LabelListView,
    LabelPrintView,
    LabelReprintView,
    LabelTrackingView,
    LabelZplView,
    PrinterConfigView,
    QzInstallView,
    TrackingWebhookView,
)

app_name = "shipping"

urlpatterns = [
    path("labels/", LabelListView.as_view(), name="label-list"),
    path("labels/create/", LabelCreateView.as_view(), name="label-create"),
    path("labels/printer-config/", PrinterConfigView.as_view(), name="printer-config"),
    path("qz-install/", QzInstallView.as_view(), name="qz-install"),
    path("labels/<int:label_id>/download/", LabelDownloadView.as_view(), name="label-download"),
    path("labels/<int:label_id>/print/", LabelPrintView.as_view(), name="label-print"),
    path("labels/<int:label_id>/reprint/", LabelReprintView.as_view(), name="label-reprint"),
    path("labels/<int:label_id>/draft-print/", DraftLabelPrintView.as_view(), name="label-draft-print"),
    path("labels/<int:label_id>/zpl/", LabelZplView.as_view(), name="label-zpl"),
    path("labels/<int:label_id>/tracking/", LabelTrackingView.as_view(), name="label-tracking"),
    path("webhooks/tracking/", TrackingWebhookView.as_view(), name="webhook-tracking"),
]
