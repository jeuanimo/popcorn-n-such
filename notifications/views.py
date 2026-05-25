from __future__ import annotations

from django.contrib import messages
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views import View
from django.utils import timezone

from core.security import RoleRequiredMixin
from notifications.forms import NotificationPreferenceForm, StaffAlertPreferenceForm
from notifications.models import (
    Notification,
    NotificationDeliveryChannel,
    NotificationDeliveryLog,
)
from notifications.alerts import NotificationService
from notifications.center import NotificationCenterService


class NotificationCenterView(RoleRequiredMixin, View):
    allowed_roles = ("staff", "admin")
    template_name = "notifications/center.html"

    def get(self, request):
        base_qs = NotificationDeliveryLog.objects.filter(
            user=request.user,
            channel=NotificationDeliveryChannel.INTERNAL,
        )
        unread_count = base_qs.filter(read_at__isnull=True).count()
        deliveries = (
            base_qs
            .select_related("event")
            .order_by("-created_at")[:100]
        )
        return render(request, self.template_name, {"deliveries": deliveries, "unread_count": unread_count})


class MarkNotificationReadView(RoleRequiredMixin, View):
    allowed_roles = ("staff", "admin")

    def post(self, request, delivery_id: int):
        delivery = get_object_or_404(NotificationDeliveryLog, id=delivery_id, user=request.user)
        delivery.mark_read()
        return HttpResponseRedirect(reverse("notifications:center"))


class MarkAllNotificationsReadView(RoleRequiredMixin, View):
    allowed_roles = ("staff", "admin")

    def post(self, request):
        NotificationDeliveryLog.objects.filter(
            user=request.user,
            channel=NotificationDeliveryChannel.INTERNAL,
            read_at__isnull=True,
        ).update(read_at=timezone.now())
        return HttpResponseRedirect(reverse("notifications:center"))


class DeleteNotificationView(RoleRequiredMixin, View):
    allowed_roles = ("staff", "admin")

    def post(self, request, delivery_id: int):
        delivery = get_object_or_404(NotificationDeliveryLog, id=delivery_id, user=request.user)
        delivery.delete()
        return HttpResponseRedirect(reverse("notifications:center"))


class DeleteAllNotificationsView(RoleRequiredMixin, View):
    allowed_roles = ("staff", "admin")

    def post(self, request):
        NotificationDeliveryLog.objects.filter(
            user=request.user,
            channel=NotificationDeliveryChannel.INTERNAL,
        ).delete()
        return HttpResponseRedirect(reverse("notifications:center"))


class UserNotificationInboxView(RoleRequiredMixin, View):
    allowed_roles = ("customer", "seller", "team_captain", "organization_manager", "staff", "admin")
    template_name = "notifications/inbox.html"

    def get(self, request):
        qs = Notification.objects.filter(user=request.user).order_by("-created_at")[:200]
        unread_count = Notification.objects.filter(user=request.user, read_at__isnull=True).count()
        return render(request, self.template_name, {"notifications": qs, "unread_count": unread_count})


class MarkUserNotificationReadView(RoleRequiredMixin, View):
    allowed_roles = ("customer", "seller", "team_captain", "organization_manager", "staff", "admin")

    def post(self, request, notification_id: int):
        n = get_object_or_404(Notification, id=notification_id, user=request.user)
        n.mark_read()
        return HttpResponseRedirect(reverse("notifications:inbox"))


class MarkAllUserNotificationsReadView(RoleRequiredMixin, View):
    allowed_roles = ("customer", "seller", "team_captain", "organization_manager", "staff", "admin")

    def post(self, request):
        Notification.objects.filter(user=request.user, read_at__isnull=True).update(read_at=timezone.now())
        return HttpResponseRedirect(reverse("notifications:inbox"))


class UserNotificationPreferencesView(RoleRequiredMixin, View):
    allowed_roles = ("customer", "seller", "team_captain", "organization_manager", "staff", "admin")
    template_name = "notifications/user_preferences.html"

    def get(self, request):
        pref = NotificationCenterService.get_or_create_preferences(request.user)
        form = NotificationPreferenceForm(instance=pref, initial={"enabled_types": pref.enabled_types})
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        pref = NotificationCenterService.get_or_create_preferences(request.user)
        form = NotificationPreferenceForm(request.POST, instance=pref)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.enabled_types = form.cleaned_data.get("enabled_types") or []
            obj.save()
            messages.success(request, "Notification preferences saved.")
            return HttpResponseRedirect(reverse("notifications:user-preferences"))
        return render(request, self.template_name, {"form": form})


class StaffAlertPreferencesView(RoleRequiredMixin, View):
    allowed_roles = ("staff", "admin")
    template_name = "notifications/preferences.html"

    def get(self, request):
        pref = NotificationService.get_or_create_preference(request.user)
        form = StaffAlertPreferenceForm(instance=pref, initial={"enabled_events": pref.enabled_events})
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        pref = NotificationService.get_or_create_preference(request.user)
        form = StaffAlertPreferenceForm(request.POST, instance=pref)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.enabled_events = form.cleaned_data.get("enabled_events") or []
            obj.save()
            messages.success(request, "Staff alert preferences saved.")
            return HttpResponseRedirect(reverse("notifications:preferences"))
        return render(request, self.template_name, {"form": form})
