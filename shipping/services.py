from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from django.conf import settings as djsettings
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.utils import timezone

from security_audit.models import AuditAction
from security_audit.utils import log_audit_event

from .carriers.base import (
    AddressInput,
    LabelRequest,
    PackageInput,
    RateRequest,
)
from .carriers.registry import get_shipping_carrier
from .models import AddressValidation, ShipmentEvent, ShippingLabel, ShippingRate

if TYPE_CHECKING:
    from accounts.models import User
    from orders.models import Order


_NOTIFY_CODES: frozenset[str] = frozenset({
    "DELIVERED", "DLVR", "01", "D",
    "OUT_FOR_DELIVERY", "OFD", "OUT FOR DELIVERY",
})


@dataclass
class TrackingEvent:
    code: str
    description: str
    timestamp: datetime.datetime
    location: str
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "description": self.description,
            "timestamp": self.timestamp.isoformat(),
            "location": self.location,
        }


_STAFF_ONLY_MSG = "Only staff/admin can create shipping labels."


@dataclass
class AddressData:
    recipient_name: str
    address_line_1: str
    city: str
    state: str
    postal_code: str
    country: str = "US"
    address_line_2: str = ""
    phone: str = ""


class ShippingService:
    def __init__(self, provider: str | None = None):
        self.carrier = get_shipping_carrier(provider)

    def validate_address(
        self,
        order: Order,
        address: AddressData,
        *,
        actor: User | None = None,
        request=None,
    ) -> AddressValidation:
        addr_input = AddressInput(
            recipient_name=address.recipient_name,
            address_line_1=address.address_line_1,
            address_line_2=address.address_line_2,
            city=address.city,
            state=address.state,
            postal_code=address.postal_code,
            country=address.country,
            phone=address.phone,
        )
        result = self.carrier.validate_address(addr_input, actor=actor, request=request)
        return AddressValidation.objects.create(
            order=order,
            provider=result.provider,
            raw_recipient_name=address.recipient_name,
            raw_address_line_1=address.address_line_1,
            raw_address_line_2=address.address_line_2,
            raw_city=address.city,
            raw_state=address.state,
            raw_postal_code=address.postal_code,
            raw_country=address.country,
            validated_address_line_1=result.validated_address_line_1 or "",
            validated_address_line_2=result.validated_address_line_2 or "",
            validated_city=result.validated_city or "",
            validated_state=result.validated_state or "",
            validated_postal_code=result.validated_postal_code or "",
            validated_country=result.validated_country or "",
            is_valid=result.is_valid,
            is_corrected=result.is_corrected,
            failure_reason=result.failure_reason or "",
            raw_response=result.raw,
            validated_by=actor,
        )

    def get_rates(
        self,
        order: Order,
        from_postal_code: str,
        package: PackageInput,
        *,
        actor: User | None = None,
        request=None,
        from_country: str = "US",
    ) -> list[ShippingRate]:
        to_address = AddressInput(
            recipient_name=order.shipping_recipient_name,
            address_line_1=order.shipping_address_line_1,
            address_line_2=order.shipping_address_line_2 or "",
            city=order.shipping_city,
            state=order.shipping_state,
            postal_code=order.shipping_postal_code,
            country=order.shipping_country,
        )
        rate_req = RateRequest(
            from_postal_code=from_postal_code,
            from_country=from_country,
            to_address=to_address,
            package=package,
            order_reference=order.order_number or str(order.pk),
        )
        quotes = self.carrier.get_rates(rate_req, actor=actor, django_request=request)
        # Clear previously fetched unselected rates for this order/provider before saving new ones
        ShippingRate.objects.filter(order=order, provider=self.carrier.slug, is_selected=False).delete()
        return [
            ShippingRate.objects.create(
                order=order,
                provider=q.provider,
                carrier=q.carrier,
                service_name=q.service_name,
                service_code=q.service_code,
                rate_cents=q.rate_cents,
                currency=q.currency,
                estimated_delivery_days=q.estimated_delivery_days,
                provider_rate_id=q.provider_rate_id,
                raw_response=q.raw,
            )
            for q in quotes
        ]

    def create_label(
        self,
        order: Order,
        shipping_rate: ShippingRate,
        from_address: AddressData,
        package: PackageInput,
        *,
        actor: User | None = None,
        request=None,
        label_format: str = "pdf_4x6",
    ) -> ShippingLabel:
        if actor is None or not getattr(actor, "is_staff", False):
            raise PermissionDenied(_STAFF_ONLY_MSG)
        if getattr(order, "status", "") not in {"paid", "processing", "packed", "shipped", "delivered"}:
            raise ValidationError("Labels may only be created after payment is confirmed.")

        to_address = AddressInput(
            recipient_name=order.shipping_recipient_name,
            address_line_1=order.shipping_address_line_1,
            address_line_2=order.shipping_address_line_2 or "",
            city=order.shipping_city,
            state=order.shipping_state,
            postal_code=order.shipping_postal_code,
            country=order.shipping_country,
        )
        from_addr_input = AddressInput(
            recipient_name=from_address.recipient_name,
            address_line_1=from_address.address_line_1,
            address_line_2=from_address.address_line_2,
            city=from_address.city,
            state=from_address.state,
            postal_code=from_address.postal_code,
            country=from_address.country,
            phone=from_address.phone,
        )
        label_req = LabelRequest(
            provider_rate_id=shipping_rate.provider_rate_id,
            from_address=from_addr_input,
            to_address=to_address,
            package=package,
            order_reference=order.order_number or str(order.pk),
            label_format=label_format,
        )
        result = self.carrier.create_label(label_req, actor=actor, django_request=request)

        shipping_rate.is_selected = True
        shipping_rate.save(update_fields=["is_selected"])

        label = ShippingLabel.objects.create(
            order=order,
            rate=shipping_rate,
            provider=result.provider,
            carrier=result.carrier,
            service_name=result.service_name,
            service_code=shipping_rate.service_code,
            tracking_number=result.tracking_number,
            tracking_url=result.tracking_url,
            label_format=result.label_format,
            label_url=result.label_url,
            rate_cents=result.rate_cents,
            provider_label_id=result.provider_label_id,
            raw_response=result.raw,
            package_weight_oz=package.weight_oz,
            package_length_in=package.length_in,
            package_width_in=package.width_in,
            package_height_in=package.height_in,
            created_by=actor,
        )
        log_audit_event(
            action=AuditAction.LABEL_CREATED,
            message=f"Shipping label created: {label.tracking_number}",
            actor=actor,
            request=request,
            metadata={
                "provider": label.provider,
                "provider_label_id": label.provider_label_id,
                "tracking_number": label.tracking_number,
                "order_id": label.order_id,
                "label_id": label.id,
            },
        )
        return label

    def create_label_v2(
        self,
        order: "Order",
        from_address: AddressData,
        package: PackageInput,
        *,
        carrier_key: str = "usps_ground",
        actor: "User | None" = None,
        request=None,
    ) -> ShippingLabel:
        """
        Create a shipping label via the Pitney Bowes v2 multi-carrier endpoint.
        The label URL is stored internally; serve it only through LabelPrintView (staff only).
        """
        if actor is None or not getattr(actor, "is_staff", False):
            raise PermissionDenied(_STAFF_ONLY_MSG)
        if getattr(order, "status", "") not in {"paid", "processing", "packed", "shipped", "delivered"}:
            raise ValidationError("Labels may only be created after payment is confirmed.")

        if not hasattr(self.carrier, "create_label_v2"):
            raise ValidationError("The configured carrier does not support v2 label creation.")

        to_address = AddressInput(
            recipient_name=order.shipping_recipient_name,
            address_line_1=order.shipping_address_line_1,
            address_line_2=order.shipping_address_line_2 or "",
            city=order.shipping_city,
            state=order.shipping_state,
            postal_code=order.shipping_postal_code,
            country=order.shipping_country,
        )
        from_addr = AddressInput(
            recipient_name=from_address.recipient_name,
            address_line_1=from_address.address_line_1,
            address_line_2=from_address.address_line_2,
            city=from_address.city,
            state=from_address.state,
            postal_code=from_address.postal_code,
            country=from_address.country,
            phone=from_address.phone,
        )
        label_req = LabelRequest(
            provider_rate_id="",
            from_address=from_addr,
            to_address=to_address,
            package=package,
            order_reference=order.order_number or str(order.pk),
            label_format="pdf_4x6",
        )
        result = self.carrier.create_label_v2(label_req, carrier_key=carrier_key, actor=actor, django_request=request)

        label = ShippingLabel.objects.create(
            order=order,
            rate=None,
            provider=result.provider,
            carrier=result.carrier,
            service_name=result.service_name,
            service_code=carrier_key,
            tracking_number=result.tracking_number,
            tracking_url=result.tracking_url,
            label_format="pdf_4x6",
            label_url=result.label_url,
            label_zpl=result.label_zpl,
            rate_cents=result.rate_cents,
            provider_label_id=result.provider_label_id,
            raw_response=result.raw,
            created_by=actor,
        )
        log_audit_event(
            action=AuditAction.LABEL_CREATED,
            message=f"Shipping label created (v2): {label.tracking_number}",
            actor=actor,
            request=request,
            metadata={
                "provider": label.provider,
                "carrier_key": carrier_key,
                "tracking_number": label.tracking_number,
                "order_id": label.order_id,
                "label_id": label.id,
            },
        )
        return label

    def create_draft_label(
        self,
        order: "Order",
        *,
        actor: "User | None" = None,
        request=None,
    ) -> ShippingLabel:
        """
        Create a draft label (no carrier API, no tracking number) so staff can
        print an address label to PDF when carrier credentials are not configured.
        """
        if actor is None or not getattr(actor, "is_staff", False):
            raise PermissionDenied(_STAFF_ONLY_MSG)

        label = ShippingLabel.objects.create(
            order=order,
            rate=None,
            provider="draft",
            carrier="",
            service_name="Draft Label",
            service_code="draft",
            tracking_number=f"DRAFT-{order.pk}",
            tracking_url="",
            label_format="pdf_4x6",
            label_url="",
            rate_cents=0,
            provider_label_id="",
            raw_response={},
            created_by=actor,
        )
        log_audit_event(
            action=AuditAction.LABEL_CREATED,
            message=f"Draft label created for order {order.order_number or order.pk}",
            actor=actor,
            request=request,
            metadata={"label_id": label.id, "order_id": order.pk},
        )
        return label

    def void_label(
        self,
        label: ShippingLabel,
        *,
        actor: User | None = None,
        request=None,
    ) -> dict:
        result = self.carrier.void_label(
            label.provider_label_id,
            actor=actor,
            django_request=request,
        )
        label.is_voided = True
        label.voided_at = timezone.now()
        label.voided_by = actor
        label.save(update_fields=["is_voided", "voided_at", "voided_by"])

        log_audit_event(
            action=AuditAction.SECURITY_EVENT,
            message=f"Shipping label voided: {label.tracking_number}",
            actor=actor,
            request=request,
            metadata={
                "provider": label.provider,
                "provider_label_id": label.provider_label_id,
                "tracking_number": label.tracking_number,
                "order_id": label.order_id,
            },
        )
        return result

    def record_reprint(
        self,
        label: ShippingLabel,
        *,
        actor: User | None = None,
        request=None,
    ) -> None:
        label.reprint_count += 1
        label.save(update_fields=["reprint_count"])

        log_audit_event(
            action=AuditAction.SECURITY_EVENT,
            message=f"Shipping label reprinted: {label.tracking_number}",
            actor=actor,
            request=request,
            metadata={
                "provider": label.provider,
                "tracking_number": label.tracking_number,
                "reprint_count": label.reprint_count,
                "order_id": label.order_id,
            },
        )

    def fetch_tracking_events(
        self,
        label: ShippingLabel,
        *,
        actor=None,
        request=None,
        notify_customer: bool = True,
    ) -> list[dict[str, Any]]:
        """Fetch live tracking from carrier, upsert into ShipmentEvent, return event list."""
        cache_key = f"shipping:tracking:{label.tracking_number}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached  # type: ignore[return-value]

        raw = self.carrier.track_shipment(label.tracking_number, actor=actor, django_request=request)
        events = self._parse_tracking_events(raw)
        self._upsert_events(label, events, notify_customer=notify_customer)

        result = [e.to_dict() for e in events]
        cache.set(cache_key, result, 300)
        return result

    @staticmethod
    def _scan_timestamp(scan: dict[str, Any]) -> datetime.datetime:
        date_str = str(scan.get("scanDate") or scan.get("date") or "").strip()
        time_str = str(scan.get("scanTime") or scan.get("time") or "00:00:00").strip()
        if date_str:
            try:
                ts = datetime.datetime.fromisoformat(f"{date_str}T{time_str}")
                return ts if ts.tzinfo else ts.replace(tzinfo=datetime.timezone.utc)
            except ValueError:
                pass
        return timezone.now()

    @staticmethod
    def _scan_location(scan: dict[str, Any]) -> str:
        city = str(scan.get("city") or "").strip()
        state = str(scan.get("stateCode") or scan.get("state") or "").strip()
        country = str(scan.get("country") or "").strip()
        return ", ".join(p for p in [city, state, country] if p)

    @classmethod
    def _parse_tracking_events(cls, raw: dict[str, Any]) -> list[TrackingEvent]:
        scan_list = raw.get("scanDetailsList") or raw.get("trackEvents") or raw.get("events") or []
        if not isinstance(scan_list, list):
            return []

        events: list[TrackingEvent] = []
        for scan in scan_list:
            code = str(scan.get("eventCode") or scan.get("eventType") or "").strip()
            description = str(
                scan.get("scanDescription") or scan.get("description") or scan.get("eventType") or "Update"
            ).strip()
            events.append(TrackingEvent(
                code=code,
                description=description,
                timestamp=cls._scan_timestamp(scan),
                location=cls._scan_location(scan),
                raw=scan,
            ))
        return events

    @staticmethod
    def _notify_tracking_event(label: ShippingLabel, event: TrackingEvent, recipient: str) -> None:
        order_ref = label.order.order_number or str(label.order.pk)
        code_upper = event.code.upper()
        is_delivered = any(c in code_upper for c in ("DELIVER", "DLVR"))
        subject = (
            f"Your order {order_ref} has been delivered!"
            if is_delivered
            else f"Your order {order_ref} is out for delivery!"
        )
        body = f"{event.description}\n\nTrack your package: {label.tracking_url}\nOrder: {order_ref}"
        try:
            send_mail(
                subject=subject,
                message=body,
                from_email=getattr(djsettings, "DEFAULT_FROM_EMAIL", None),
                recipient_list=[recipient],
                fail_silently=True,
            )
        except Exception:
            pass

    @classmethod
    def _upsert_events(
        cls,
        label: ShippingLabel,
        events: list[TrackingEvent],
        *,
        notify_customer: bool = True,
    ) -> None:
        customer = getattr(label.order, "customer", None)
        customer_email = getattr(customer, "email", None) or getattr(label.order, "guest_email", None)

        for event in events:
            _obj, created = ShipmentEvent.objects.get_or_create(
                label=label,
                event_code=event.code,
                event_timestamp=event.timestamp,
                defaults={
                    "event_description": event.description,
                    "location": event.location,
                    "raw": event.raw,
                },
            )
            if created and notify_customer and customer_email:
                code_upper = event.code.upper()
                is_notable = (
                    any(c in code_upper for c in ("DELIVER", "DLVR", "OUT_FOR", "OFD"))
                    or code_upper in _NOTIFY_CODES
                )
                if is_notable:
                    cls._notify_tracking_event(label, event, customer_email)
