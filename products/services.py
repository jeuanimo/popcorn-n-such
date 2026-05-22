from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from core.validators import validate_remote_image_url
from security_audit.models import AuditAction
from security_audit.utils import log_audit_event

from .models import CSVImportBatch, CSVImportBatchStatus, CSVImportRowError, Product, ProductCategory, SKU


CSV_REQUIRED_COLUMNS = [
    "sku",
    "product_name",
    "category",
    "flavor",
    "size",
    "description",
    "cost_price",
    "retail_price",
    "inventory_count",
    "low_stock_threshold",
    "weight_oz",
    "is_active",
    "fundraiser_eligible",
    "standalone_store_eligible",
]

TRUE_VALUES = {"1", "true", "yes", "y", "on"}
FALSE_VALUES = {"0", "false", "no", "n", "off"}


@dataclass
class PaymentConfirmedLineItem:
    sku_code: str
    quantity: int


class InventoryAllocationService:
    @staticmethod
    def apply_post_payment_deductions(line_items: list[PaymentConfirmedLineItem]):
        for line_item in line_items:
            sku = SKU.objects.select_for_update().get(sku_code=line_item.sku_code)
            sku.decrease_inventory(line_item.quantity, payment_confirmed=True)


class ProductSKUCSVImportService:
    @staticmethod
    def _parse_bool(value: str, *, field_name: str) -> bool:
        normalized = (value or "").strip().lower()
        if normalized in TRUE_VALUES:
            return True
        if normalized in FALSE_VALUES:
            return False
        raise ValidationError(f"Invalid boolean for {field_name}.")

    @staticmethod
    def _parse_decimal(value: str, *, field_name: str) -> Decimal:
        try:
            return Decimal((value or "").strip())
        except (InvalidOperation, ValueError) as exc:
            raise ValidationError(f"Invalid decimal for {field_name}.") from exc

    @staticmethod
    def _parse_int(value: str, *, field_name: str) -> int:
        try:
            result = int((value or "").strip())
        except ValueError as exc:
            raise ValidationError(f"Invalid integer for {field_name}.") from exc
        if result < 0:
            raise ValidationError(f"{field_name} cannot be negative.")
        return result

    @classmethod
    def _normalize_rows(cls, payload: str) -> tuple[list[dict], list[dict]]:
        reader = csv.DictReader(io.StringIO(payload))
        if not reader.fieldnames:
            raise ValidationError("CSV header is missing.")

        missing_columns = [column for column in CSV_REQUIRED_COLUMNS if column not in reader.fieldnames]
        if missing_columns:
            raise ValidationError(f"Missing required CSV columns: {', '.join(missing_columns)}")

        normalized_rows: list[dict] = []
        row_errors: list[dict] = []
        seen_skus: set[str] = set()

        for row_number, row in enumerate(reader, start=2):
            sku = (row.get("sku") or "").strip()
            error_messages = []

            if not sku:
                error_messages.append("sku is required.")
            elif sku in seen_skus:
                error_messages.append("Duplicate SKU within uploaded CSV.")
            seen_skus.add(sku)

            for required in CSV_REQUIRED_COLUMNS:
                if not (row.get(required) or "").strip():
                    error_messages.append(f"{required} is required.")

            if error_messages:
                row_errors.append({"row_number": row_number, "sku": sku, "error": " ".join(error_messages), "row": row})
                continue

            try:
                normalized = {
                    "sku": sku,
                    "product_name": row["product_name"].strip(),
                    "category": row["category"].strip(),
                    "flavor": row["flavor"].strip(),
                    "size": row["size"].strip(),
                    "description": row["description"].strip(),
                    "cost_price": str(cls._parse_decimal(row["cost_price"], field_name="cost_price")),
                    "retail_price": str(cls._parse_decimal(row["retail_price"], field_name="retail_price")),
                    "inventory_count": cls._parse_int(row["inventory_count"], field_name="inventory_count"),
                    "low_stock_threshold": cls._parse_int(row["low_stock_threshold"], field_name="low_stock_threshold"),
                    "weight_oz": str(cls._parse_decimal(row["weight_oz"], field_name="weight_oz")),
                    "is_active": cls._parse_bool(row["is_active"], field_name="is_active"),
                    "fundraiser_eligible": cls._parse_bool(row["fundraiser_eligible"], field_name="fundraiser_eligible"),
                    "standalone_store_eligible": cls._parse_bool(
                        row["standalone_store_eligible"], field_name="standalone_store_eligible"
                    ),
                    "image_url": (row.get("image_url") or "").strip(),
                }

                if normalized["image_url"]:
                    validate_remote_image_url(normalized["image_url"])

                normalized_rows.append(normalized)
            except ValidationError as exc:
                row_errors.append({"row_number": row_number, "sku": sku, "error": str(exc), "row": row})

        return normalized_rows, row_errors

    @classmethod
    def preview_import(cls, *, csv_file, uploader, request=None) -> CSVImportBatch:
        payload = csv_file.read().decode("utf-8")
        csv_file.seek(0)

        normalized_rows, row_errors = cls._normalize_rows(payload)

        batch = CSVImportBatch.objects.create(
            uploader=uploader,
            uploaded_filename=csv_file.name,
            status=CSVImportBatchStatus.PREVIEWED,
            total_rows=len(normalized_rows) + len(row_errors),
            valid_rows=len(normalized_rows),
            invalid_rows=len(row_errors),
            preview_payload=normalized_rows,
        )

        for row_error in row_errors:
            CSVImportRowError.objects.create(
                batch=batch,
                row_number=row_error["row_number"],
                sku=row_error["sku"],
                error_message=row_error["error"],
                row_data=row_error["row"],
            )

        log_audit_event(
            action=AuditAction.CSV_UPLOAD,
            message="Products/SKUs CSV preview generated",
            actor=uploader,
            request=request,
            target=batch,
            metadata={
                "filename": csv_file.name,
                "valid_rows": batch.valid_rows,
                "invalid_rows": batch.invalid_rows,
            },
        )
        return batch

    @classmethod
    @transaction.atomic
    def commit_import(cls, *, batch: CSVImportBatch, actor, request=None) -> CSVImportBatch:
        if batch.status != CSVImportBatchStatus.PREVIEWED:
            raise ValidationError("Only previewed batches can be committed.")
        if batch.invalid_rows > 0:
            raise ValidationError("Resolve row errors before committing import.")

        operations = []
        created_skus = 0
        updated_skus = 0
        created_product_ids: set[int] = set()
        created_category_ids: set[int] = set()
        existing_product_snapshots: dict[int, dict] = {}

        for row in batch.preview_payload:
            category_key = slugify(row["category"])
            category, category_created = ProductCategory.objects.get_or_create(
                key=category_key,
                defaults={"name": row["category"], "is_active": True},
            )
            if category_created:
                created_category_ids.add(category.id)

            product_slug = slugify(row["product_name"])
            product, product_created = Product.objects.get_or_create(
                slug=product_slug,
                defaults={
                    "name": row["product_name"],
                    "description": row["description"],
                    "category": category,
                    "flavor": row["flavor"],
                    "external_image_url": row["image_url"],
                    "is_active": row["is_active"],
                    "fundraiser_eligible": row["fundraiser_eligible"],
                    "standalone_store_eligible": row["standalone_store_eligible"],
                },
            )

            if product_created:
                created_product_ids.add(product.id)
            else:
                if product.id not in existing_product_snapshots:
                    existing_product_snapshots[product.id] = {
                        "name": product.name,
                        "description": product.description,
                        "category_id": product.category_id,
                        "flavor": product.flavor,
                        "external_image_url": product.external_image_url,
                        "is_active": product.is_active,
                        "fundraiser_eligible": product.fundraiser_eligible,
                        "standalone_store_eligible": product.standalone_store_eligible,
                    }
                product.name = row["product_name"]
                product.description = row["description"]
                product.category = category
                product.flavor = row["flavor"]
                product.external_image_url = row["image_url"]
                product.is_active = row["is_active"]
                product.fundraiser_eligible = row["fundraiser_eligible"]
                product.standalone_store_eligible = row["standalone_store_eligible"]
                product.save()

            sku = SKU.objects.filter(sku_code=row["sku"]).first()
            if sku:
                operations.append(
                    {
                        "action": "update_sku",
                        "sku_id": sku.id,
                        "before": {
                            "product_id": sku.product_id,
                            "size": sku.size,
                            "retail_price": str(sku.retail_price),
                            "cost_price": str(sku.cost_price),
                            "weight_ounces": str(sku.weight_ounces),
                            "inventory_quantity": sku.inventory_quantity,
                            "low_stock_threshold": sku.low_stock_threshold,
                            "is_active": sku.is_active,
                        },
                    }
                )
                sku.product = product
                sku.size = row["size"]
                sku.retail_price = row["retail_price"]
                sku.cost_price = row["cost_price"]
                sku.weight_ounces = row["weight_oz"]
                sku.inventory_quantity = row["inventory_count"]
                sku.low_stock_threshold = row["low_stock_threshold"]
                sku.is_active = row["is_active"]
                sku.save()
                updated_skus += 1
            else:
                sku = SKU.objects.create(
                    sku_code=row["sku"],
                    product=product,
                    size=row["size"],
                    retail_price=row["retail_price"],
                    cost_price=row["cost_price"],
                    weight_ounces=row["weight_oz"],
                    inventory_quantity=row["inventory_count"],
                    low_stock_threshold=row["low_stock_threshold"],
                    is_active=row["is_active"],
                )
                operations.append({"action": "create_sku", "sku_id": sku.id})
                created_skus += 1

        batch.created_skus = created_skus
        batch.updated_skus = updated_skus
        batch.rollback_payload = {
            "operations": operations,
            "created_product_ids": list(created_product_ids),
            "created_category_ids": list(created_category_ids),
            "existing_product_snapshots": existing_product_snapshots,
        }
        batch.status = CSVImportBatchStatus.COMMITTED
        batch.committed_at = timezone.now()
        batch.save(
            update_fields=[
                "created_skus",
                "updated_skus",
                "rollback_payload",
                "status",
                "committed_at",
            ]
        )

        log_audit_event(
            action=AuditAction.CSV_UPLOAD,
            message="Products/SKUs CSV import committed",
            actor=actor,
            request=request,
            target=batch,
            metadata={"created_skus": created_skus, "updated_skus": updated_skus},
        )
        try:
            from notifications.alerts import NotificationService
            from notifications.models import StaffAlertEventType

            NotificationService.emit_event(
                event_type=StaffAlertEventType.CSV_IMPORT_COMPLETED,
                title=f"CSV import committed (batch #{batch.id})",
                message=f"Created SKUs: {created_skus}, Updated SKUs: {updated_skus}",
                severity="info",
                payload={"batch_id": batch.id, "created_skus": created_skus, "updated_skus": updated_skus},
                dedupe_key=f"csv_commit:{batch.id}",
                actor=actor,
                request=request,
            )
        except Exception:
            pass
        return batch

    @classmethod
    @transaction.atomic
    def rollback_last_import(cls, *, actor, request=None) -> CSVImportBatch:
        batch = (
            CSVImportBatch.objects.select_for_update()
            .filter(status=CSVImportBatchStatus.COMMITTED)
            .order_by("-committed_at")
            .first()
        )
        if not batch:
            raise ValidationError("No committed CSV import available to roll back.")

        payload = batch.rollback_payload or {}
        for operation in reversed(payload.get("operations", [])):
            action = operation.get("action")
            sku_id = operation.get("sku_id")
            sku = SKU.objects.filter(id=sku_id).first()

            if action == "create_sku":
                if sku:
                    sku.delete()
            elif action == "update_sku" and sku:
                before = operation.get("before", {})
                sku.product_id = before.get("product_id", sku.product_id)
                sku.size = before.get("size", sku.size)
                sku.retail_price = Decimal(before.get("retail_price", str(sku.retail_price)))
                sku.cost_price = Decimal(before.get("cost_price", str(sku.cost_price)))
                sku.weight_ounces = Decimal(before.get("weight_ounces", str(sku.weight_ounces)))
                sku.inventory_quantity = before.get("inventory_quantity", sku.inventory_quantity)
                sku.low_stock_threshold = before.get("low_stock_threshold", sku.low_stock_threshold)
                sku.is_active = before.get("is_active", sku.is_active)
                sku.save()

        for product_id in payload.get("created_product_ids", []):
            product = Product.objects.filter(id=product_id).first()
            if product and not product.skus.exists():
                product.delete()

        for product_id, snapshot in (payload.get("existing_product_snapshots") or {}).items():
            product = Product.objects.filter(id=int(product_id)).first()
            if not product:
                continue
            product.name = snapshot.get("name", product.name)
            product.description = snapshot.get("description", product.description)
            product.category_id = snapshot.get("category_id", product.category_id)
            product.flavor = snapshot.get("flavor", product.flavor)
            product.external_image_url = snapshot.get("external_image_url", product.external_image_url)
            product.is_active = snapshot.get("is_active", product.is_active)
            product.fundraiser_eligible = snapshot.get("fundraiser_eligible", product.fundraiser_eligible)
            product.standalone_store_eligible = snapshot.get(
                "standalone_store_eligible", product.standalone_store_eligible
            )
            product.save()

        for category_id in payload.get("created_category_ids", []):
            category = ProductCategory.objects.filter(id=category_id).first()
            if category and not category.products.exists():
                category.delete()

        batch.status = CSVImportBatchStatus.ROLLED_BACK
        batch.rolled_back_at = timezone.now()
        batch.save(update_fields=["status", "rolled_back_at"])

        log_audit_event(
            action=AuditAction.CSV_UPLOAD,
            message="Products/SKUs CSV import rolled back",
            actor=actor,
            request=request,
            target=batch,
        )
        return batch
