from django.urls import path

from notifications import views

app_name = "notifications"

urlpatterns = [
    path("center/", views.NotificationCenterView.as_view(), name="center"),
    path("center/read/<int:delivery_id>/", views.MarkNotificationReadView.as_view(), name="mark-read"),
    path("center/read-all/", views.MarkAllNotificationsReadView.as_view(), name="mark-all-read"),
    path("preferences/", views.StaffAlertPreferencesView.as_view(), name="preferences"),

    path("inbox/", views.UserNotificationInboxView.as_view(), name="inbox"),
    path("inbox/read/<int:notification_id>/", views.MarkUserNotificationReadView.as_view(), name="inbox-mark-read"),
    path("inbox/read-all/", views.MarkAllUserNotificationsReadView.as_view(), name="inbox-mark-all-read"),
    path("settings/", views.UserNotificationPreferencesView.as_view(), name="user-preferences"),
]
