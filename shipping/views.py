from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings as djsettings
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from core.runtime_settings import get_runtime_setting
from security_audit.models import AuditAction
from security_audit.utils import log_audit_event

from .gateways.pitney_bowes import PitneyBowesProviderError
from .models import ShippingLabel
from .services import AddressData, ShippingService
from .carriers.base import PackageInput

_PDF_CONTENT_TYPE = "application/pdf"


CARRIER_CHOICES: list[tuple[str, str]] = [
    ("usps_ground", "USPS Ground Advantage"),
    ("fedex_ground", "FedEx Ground"),
    ("ups_ground", "UPS Ground"),
]
_VALID_CARRIER_KEYS: frozenset[str] = frozenset(k for k, _ in CARRIER_CHOICES)


def _allowed_remote_hosts() -> set[str]:
    """Return host allowlist for remote fetches (labels, vendor JS)."""
    configured = get_runtime_setting("ALLOWED_REMOTE_IMAGE_HOSTS", getattr(djsettings, "ALLOWED_REMOTE_IMAGE_HOSTS", ""))
    hosts: set[str] = set()
    if isinstance(configured, (list, tuple, set)):
        hosts.update(str(h).strip().lower() for h in configured if str(h).strip())
    else:
        raw = str(configured or "")
        hosts.update(h.strip().lower() for h in raw.split(",") if h.strip())
    hosts.add("cdn.qz.io")
    return hosts


def _is_allowed_remote_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower().strip()
    if not host:
        return False
    return host in _allowed_remote_hosts()


def _safe_fetch_remote_bytes(url: str, *, timeout: int = 15, max_bytes: int | None = None) -> bytes:
    if not _is_allowed_remote_url(url):
        raise Http404("Remote file URL is not allowed.")
    with urllib.request.urlopen(url, timeout=timeout) as remote:
        if max_bytes is None:
            return remote.read()
        data = remote.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise Http404("Remote file exceeds size limit.")
        return data


def _from_address_from_settings() -> AddressData:
    """Build the ship-from address using runtime/env/settings, in that priority order."""
    def _get(key: str, fallback: str = "") -> str:
        from django.conf import settings as djsettings
        return str(get_runtime_setting(key, getattr(djsettings, key, "") or fallback)).strip()

    return AddressData(
        recipient_name=_get("SHIPPING_FROM_NAME", "Popcorn N Such"),
        address_line_1=_get("SHIPPING_FROM_ADDRESS_LINE_1"),
        address_line_2=_get("SHIPPING_FROM_ADDRESS_LINE_2"),
        city=_get("SHIPPING_FROM_CITY"),
        state=_get("SHIPPING_FROM_STATE"),
        postal_code=_get("SHIPPING_FROM_POSTAL_CODE", "00000"),
        country=_get("SHIPPING_FROM_COUNTRY", "US"),
    )


def _default_package(order=None) -> PackageInput:
    from django.conf import settings as djsettings
    default_oz = float(
        get_runtime_setting("SHIPPING_DEFAULT_WEIGHT_OZ", getattr(djsettings, "SHIPPING_DEFAULT_WEIGHT_OZ", 16)) or 16
    )
    weight = default_oz
    if order is not None:
        total = sum(float(item.weight_ounces or default_oz) * item.quantity for item in order.items.all())
        if total > 0:
            weight = total
    return PackageInput(weight_oz=weight, length_in=12.0, width_in=8.0, height_in=6.0)


@method_decorator(staff_member_required, name="dispatch")
class LabelListView(View):
    """Staff label monitor: searchable list of all shipping labels."""

    def get(self, request) -> HttpResponse:
        q = (request.GET.get("q") or "").strip()
        qs = ShippingLabel.objects.select_related("order").order_by("-created_at")
        if q:
            qs = qs.filter(tracking_number__icontains=q) | ShippingLabel.objects.filter(
                order__order_number__icontains=q
            ).select_related("order").order_by("-created_at")
            qs = qs.distinct().order_by("-created_at")
        labels = qs[:200]
        return render(request, "shipping/labels.html", {
            "labels": labels,
            "q": q,
            "carrier_choices": CARRIER_CHOICES,
        })


@method_decorator(staff_member_required, name="dispatch")
class LabelCreateView(View):
    """
    GET  — render the Generate & Print UI.
    POST — JSON endpoint: { order_ref, carrier_key } → { label_id, tracking_number, carrier,
           service_name, cost, print_url }
    """

    def get(self, request) -> HttpResponse:
        from orders.models import Order
        eligible_orders = (
            Order.objects.filter(
                status__in=["paid", "processing", "packed", "shipped", "delivered"]
            )
            .order_by("-created_at")
            .values("id", "order_number", "shipping_recipient_name", "status", "created_at")[:500]
        )
        return render(request, "shipping/label_create.html", {
            "carrier_choices": CARRIER_CHOICES,
            "eligible_orders": list(eligible_orders),
        })

    @staticmethod
    def _dispatch_tracking_email(label) -> None:
        if label.order_id:
            from shipping.tasks import send_tracking_email
            send_tracking_email.delay(label.order_id, label.id)

    @staticmethod
    def _try_draft_fallback(request, svc, order, exc) -> JsonResponse | None:
        """Return a draft-label JSON response whenever the carrier API fails."""
        try:
            label = svc.create_draft_label(order, actor=request.user, request=request)
            draft_url = request.build_absolute_uri(f"/shipping/labels/{label.id}/draft-print/")
            return JsonResponse({
                "label_id": label.id,
                "tracking_number": label.tracking_number,
                "tracking_url": "",
                "carrier": "Draft",
                "service_name": "No Carrier",
                "cost": "$0.00",
                "print_url": draft_url,
                "has_zpl": False,
                "draft": True,
            })
        except Exception:
            return None

    def post(self, request) -> JsonResponse:
        from orders.models import Order

        if not request.content_type or not request.content_type.startswith("application/json"):
            return JsonResponse({"error": "Content-Type must be application/json."}, status=415)

        try:
            body = json.loads(request.body)
        except ValueError:
            return JsonResponse({"error": "Invalid JSON body."}, status=400)

        order_ref = str(body.get("order_ref") or "").strip()
        carrier_key = str(body.get("carrier_key") or "usps_ground").strip()

        if not order_ref:
            return JsonResponse({"error": "Order number is required."}, status=400)
        if carrier_key not in _VALID_CARRIER_KEYS:
            return JsonResponse({"error": "Invalid carrier selection."}, status=400)

        order = Order.objects.filter(order_number=order_ref).first()
        if order is None and order_ref.isdigit():
            order = Order.objects.filter(pk=int(order_ref)).first()
        if order is None:
            return JsonResponse({"error": f"Order '{order_ref}' not found."}, status=404)

        svc = ShippingService(provider="pitney_bowes")
        try:
            label = svc.create_label_v2(
                order=order,
                from_address=_from_address_from_settings(),
                package=_default_package(order),
                carrier_key=carrier_key,
                actor=request.user,
                request=request,
            )
        except PermissionDenied as exc:
            return JsonResponse({"error": str(exc)}, status=403)
        except ValidationError as exc:
            return JsonResponse({"error": " ".join(exc.messages)}, status=400)
        except PitneyBowesProviderError as exc:
            fallback = self._try_draft_fallback(request, svc, order, exc)
            if fallback is not None:
                return fallback
            return JsonResponse({"error": f"Label creation failed: {exc}"}, status=502)

        self._dispatch_tracking_email(label)

        print_url = request.build_absolute_uri(f"/shipping/labels/{label.id}/print/")
        return JsonResponse({
            "label_id": label.id,
            "tracking_number": label.tracking_number,
            "tracking_url": label.tracking_url,
            "carrier": label.carrier,
            "service_name": label.service_name,
            "cost": f"${label.rate_cents / 100:.2f}",
            "print_url": print_url,
            "has_zpl": bool(label.label_zpl),
        })


@method_decorator(staff_member_required, name="dispatch")
class LabelPrintView(View):
    """Serve the label PDF inline (Content-Disposition: inline) for iframe printing."""

    def get(self, request, label_id: int) -> HttpResponse:
        label = get_object_or_404(ShippingLabel, pk=label_id)

        if label.provider == "draft":
            draft_view = DraftLabelPrintView()
            draft_view.request = request
            return draft_view.get(request, label_id)

        is_reprint = label.print_count > 0
        update_fields = ["print_count"]
        label.print_count += 1
        if not label.first_printed_at:
            label.first_printed_at = timezone.now()
            update_fields.append("first_printed_at")
        label.save(update_fields=update_fields)

        log_audit_event(
            action=AuditAction.SECURITY_EVENT,
            message=f"Shipping label {'reprinted' if is_reprint else 'printed'}: {label.tracking_number}",
            actor=request.user,
            request=request,
            metadata={
                "label_id": label_id,
                "tracking_number": label.tracking_number,
                "print_count": label.print_count,
            },
        )

        try:
            from notifications.center import NotificationCenterService
            NotificationCenterService.notify_label_printed(
                user=request.user, label=label, is_reprint=is_reprint
            )
        except Exception:  # noqa: BLE001 — never let notification failure block label serving
            pass

        filename = f"label_{label.tracking_number}.pdf"

        if label.label_file:
            response = FileResponse(label.label_file.open("rb"), content_type=_PDF_CONTENT_TYPE)
            response["Content-Disposition"] = f'inline; filename="{filename}"'
            return response

        if label.label_url:
            try:
                content = _safe_fetch_remote_bytes(label.label_url, timeout=15)
                response = HttpResponse(content, content_type=_PDF_CONTENT_TYPE)
                response["Content-Disposition"] = f'inline; filename="{filename}"'
                return response
            except Exception:
                raise Http404("Label PDF could not be retrieved.")

        raise Http404("Label file has not been generated yet.")


@method_decorator(staff_member_required, name="dispatch")
class LabelDownloadView(View):
    """Stream label as a file attachment (for download). Never redirects to raw label URL."""

    def get(self, request, label_id: int) -> HttpResponse:
        label = get_object_or_404(ShippingLabel, pk=label_id)

        log_audit_event(
            action=AuditAction.SECURITY_EVENT,
            message=f"Shipping label downloaded: {label.tracking_number}",
            actor=request.user,
            request=request,
            metadata={
                "label_id": label_id,
                "provider": label.provider,
                "tracking_number": label.tracking_number,
                "order_id": label.order_id,
            },
        )

        ext = "pdf" if label.label_format == "pdf_4x6" else "zpl"
        content_type = _PDF_CONTENT_TYPE if label.label_format == "pdf_4x6" else "application/octet-stream"
        filename = f"label_{label.tracking_number}.{ext}"

        if label.label_file:
            response = FileResponse(label.label_file.open("rb"), content_type=content_type)
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
            return response

        if label.label_url:
            try:
                content = _safe_fetch_remote_bytes(label.label_url, timeout=15)
                response = HttpResponse(content, content_type=content_type)
                response["Content-Disposition"] = f'attachment; filename="{filename}"'
                return response
            except Exception:
                raise Http404("Label file is not available.")

        raise Http404("Label file has not been generated yet.")


@method_decorator(staff_member_required, name="dispatch")
class LabelReprintView(View):
    """Record a reprint event and re-serve the label."""

    def post(self, request, label_id: int) -> HttpResponse:
        label = get_object_or_404(ShippingLabel, pk=label_id)
        if label.is_voided:
            return HttpResponse("Label has been voided and cannot be reprinted.", status=400)

        if label.provider == "draft":
            draft_view = DraftLabelPrintView()
            draft_view.request = request
            return draft_view.get(request, label_id)

        svc = ShippingService(provider=label.provider)
        svc.record_reprint(label, actor=request.user, request=request)

        download_view = LabelDownloadView()
        download_view.request = request
        return download_view.get(request, label_id)


@method_decorator(staff_member_required, name="dispatch")
class LabelZplView(View):
    """Return raw ZPL for a label so QZ Tray can send it directly to the thermal printer."""

    def get(self, request, label_id: int) -> JsonResponse:
        label = get_object_or_404(ShippingLabel, pk=label_id)
        if not label.label_zpl:
            return JsonResponse({"error": "No ZPL data available for this label."}, status=404)
        return JsonResponse({"zpl": label.label_zpl})


@method_decorator(staff_member_required, name="dispatch")
class PrinterConfigView(View):
    """Return label printer name and IP from runtime settings for the QZ Tray client."""

    def get(self, request) -> JsonResponse:
        printer_name = str(get_runtime_setting("LABEL_PRINTER_NAME", "") or "").strip()
        printer_ip = str(get_runtime_setting("LABEL_PRINTER_IP", "") or "").strip()
        return JsonResponse({"printer_name": printer_name, "printer_ip": printer_ip})


@method_decorator(staff_member_required, name="dispatch")
class DraftLabelPrintView(View):
    """Render a printable HTML address label for draft (no-carrier) labels."""

    def get(self, request, label_id: int) -> HttpResponse:
        label = get_object_or_404(ShippingLabel, pk=label_id, provider="draft")

        is_reprint = label.print_count > 0
        label.print_count += 1
        update_fields = ["print_count"]
        if not label.first_printed_at:
            label.first_printed_at = timezone.now()
            update_fields.append("first_printed_at")
        label.save(update_fields=update_fields)

        log_audit_event(
            action=AuditAction.SECURITY_EVENT,
            message=f"Draft label {'reprinted' if is_reprint else 'printed'}: {label.tracking_number}",
            actor=request.user,
            request=request,
            metadata={"label_id": label_id},
        )

        from_addr = _from_address_from_settings()
        return render(request, "shipping/draft_label.html", {
            "label": label,
            "from_addr": from_addr,
            "order": label.order,
        })


@method_decorator(login_required, name="dispatch")
class LabelTrackingView(View):
    """
    GET  → JSON tracking events for a label.
    Accessible by the order owner or any staff member.
    Falls back to stored ShipmentEvent rows if the carrier API fails.
    """

    def get(self, request, label_id: int) -> JsonResponse:
        label = get_object_or_404(ShippingLabel, pk=label_id)

        if not request.user.is_staff:
            order_customer_id = getattr(label.order, "customer_id", None)
            if order_customer_id != request.user.pk:
                raise PermissionDenied

        if label.provider == "draft" or not label.tracking_number:
            return JsonResponse({"events": [], "status": "draft"})

        svc = ShippingService(provider=label.provider)
        try:
            events = svc.fetch_tracking_events(label, actor=request.user, request=request)
            return JsonResponse({"events": events, "status": "live"})
        except Exception:
            stored = list(
                label.events.values("event_code", "event_description", "event_timestamp", "location")[:30]
            )
            for row in stored:
                if hasattr(row.get("event_timestamp"), "isoformat"):
                    row["event_timestamp"] = row["event_timestamp"].isoformat()
            return JsonResponse({"events": stored, "status": "cached"})


@method_decorator(csrf_exempt, name="dispatch")
class TrackingWebhookView(View):
    """
    POST  — receive push tracking events from Pitney Bowes.
    Verifies an optional shared secret header (X-PB-Webhook-Secret).
    """

    def post(self, request) -> JsonResponse:
        import os
        expected_secret = os.getenv("SHIPPING_WEBHOOK_SECRET", "").strip()
        if expected_secret:
            incoming = request.headers.get("X-PB-Webhook-Secret", "").strip()
            if incoming != expected_secret:
                return JsonResponse({"error": "Forbidden"}, status=403)

        try:
            payload = json.loads(request.body)
        except ValueError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        tracking_number = str(payload.get("trackingNumber") or payload.get("parcelTrackingNumber") or "").strip()
        if not tracking_number:
            return JsonResponse({"error": "trackingNumber required"}, status=400)

        label = ShippingLabel.objects.filter(tracking_number=tracking_number, is_voided=False).first()
        if label is None:
            return JsonResponse({"ok": True, "note": "unknown tracking number"})

        svc = ShippingService(provider=label.provider)
        events = svc._parse_tracking_events(payload)
        svc._upsert_events(label, events, notify_customer=True)
        return JsonResponse({"ok": True, "events_received": len(events)})


_QZ_CDN_URL = "https://cdn.qz.io/qz-tray/qz-tray.js"
_QZ_DEST = Path(djsettings.BASE_DIR) / "static" / "js" / "vendor" / "qz-tray.js"
_QZ_MAX_BYTES = 5 * 1024 * 1024  # 5 MB safety cap


@method_decorator(staff_member_required, name="dispatch")
class QzInstallView(View):
    """
    GET  — report whether qz-tray.js is already on disk.
    POST — download qz-tray.js from the official CDN and save to static/js/vendor/.
    """

    def get(self, request) -> JsonResponse:
        installed = _QZ_DEST.exists()
        size_kb = round(_QZ_DEST.stat().st_size / 1024) if installed else 0
        return JsonResponse({"installed": installed, "size_kb": size_kb})

    def post(self, request) -> JsonResponse:
        try:
            _QZ_DEST.parent.mkdir(parents=True, exist_ok=True)
            content = _safe_fetch_remote_bytes(_QZ_CDN_URL, timeout=30, max_bytes=_QZ_MAX_BYTES)
            _QZ_DEST.write_bytes(content)
        except Exception as exc:
            return JsonResponse({"error": f"Download failed: {exc}"}, status=502)

        log_audit_event(
            action=AuditAction.SECURITY_EVENT,
            message="QZ Tray JS library installed from CDN",
            actor=request.user,
            request=request,
            metadata={"dest": str(_QZ_DEST), "size_kb": round(len(content) / 1024)},
        )
        return JsonResponse({"ok": True, "size_kb": round(len(content) / 1024)})
