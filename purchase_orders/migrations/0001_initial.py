from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from django.utils import timezone


class Migration(migrations.Migration):

	initial = True

	dependencies = [
		migrations.swappable_dependency(settings.AUTH_USER_MODEL),
		("products", "0004_product_external_image_url_csvimportbatch_and_more"),
		("supplies", "0001_initial"),
		("suppliers", "0001_initial"),
	]

	operations = [
		migrations.CreateModel(
			name="PurchaseOrder",
			fields=[
				("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
				("po_number", models.CharField(db_index=True, max_length=60, unique=True)),
				(
					"status",
					models.CharField(
						choices=[
							("draft", "Draft"),
							("submitted", "Submitted"),
							("ordered", "Ordered"),
							("partially_received", "Partially Received"),
							("received", "Received"),
							("canceled", "Canceled"),
							("paid", "Paid"),
						],
						default="draft",
						max_length=24,
					),
				),
				("order_date", models.DateField(default=timezone.localdate)),
				("expected_delivery_date", models.DateField(blank=True, null=True)),
				("received_date", models.DateField(blank=True, null=True)),
				("subtotal_cents", models.PositiveIntegerField(default=0)),
				("tax_cents", models.PositiveIntegerField(default=0)),
				("shipping_cents", models.PositiveIntegerField(default=0)),
				("total_cents", models.PositiveIntegerField(default=0)),
				("currency", models.CharField(default="USD", max_length=10)),
				("notes", models.TextField(blank=True)),
				("invoice_file", models.FileField(blank=True, upload_to="purchase_orders/invoices/%Y/%m/%d/")),
				("created_at", models.DateTimeField(auto_now_add=True)),
				("updated_at", models.DateTimeField(auto_now=True)),
				(
					"created_by",
					models.ForeignKey(
						blank=True,
						null=True,
						on_delete=django.db.models.deletion.SET_NULL,
						related_name="created_purchase_orders",
						to=settings.AUTH_USER_MODEL,
					),
				),
				(
					"supplier",
					models.ForeignKey(
						on_delete=django.db.models.deletion.PROTECT,
						related_name="purchase_orders_v2",
						to="suppliers.supplier",
					),
				),
			],
			options={
				"ordering": ["-created_at"],
				"indexes": [models.Index(fields=["supplier", "status"], name="purchase_orders_po_supplier_status_idx")],
			},
		),
		migrations.CreateModel(
			name="PurchaseOrderItem",
			fields=[
				("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
				("description", models.CharField(blank=True, max_length=255)),
				("quantity_ordered", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
				("quantity_received", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
				("unit_cost_cents", models.PositiveIntegerField(default=0)),
				("line_total_cents", models.PositiveIntegerField(default=0)),
				("created_at", models.DateTimeField(auto_now_add=True)),
				("updated_at", models.DateTimeField(auto_now=True)),
				(
					"purchase_order",
					models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="items", to="purchase_orders.purchaseorder"),
				),
				(
					"sku",
					models.ForeignKey(
						blank=True,
						null=True,
						on_delete=django.db.models.deletion.PROTECT,
						related_name="purchase_order_items",
						to="products.sku",
					),
				),
				(
					"supply",
					models.ForeignKey(
						blank=True,
						null=True,
						on_delete=django.db.models.deletion.PROTECT,
						related_name="purchase_order_items",
						to="supplies.supply",
					),
				),
			],
			options={
				"ordering": ["id"],
				"indexes": [models.Index(fields=["purchase_order"], name="purchase_orders_item_po_idx")],
			},
		),
		migrations.CreateModel(
			name="ReceivingEvent",
			fields=[
				("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
				("received_delta", models.DecimalField(decimal_places=2, max_digits=12)),
				("override_used", models.BooleanField(default=False)),
				("notes", models.CharField(blank=True, max_length=255)),
				("received_at", models.DateTimeField(auto_now_add=True)),
				(
					"item",
					models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="receiving_events", to="purchase_orders.purchaseorderitem"),
				),
				(
					"purchase_order",
					models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="receiving_events", to="purchase_orders.purchaseorder"),
				),
				(
					"received_by",
					models.ForeignKey(
						blank=True,
						null=True,
						on_delete=django.db.models.deletion.SET_NULL,
						related_name="purchase_order_receiving_events",
						to=settings.AUTH_USER_MODEL,
					),
				),
			],
			options={
				"ordering": ["-received_at"],
				"indexes": [models.Index(fields=["purchase_order", "received_at"], name="purchase_orders_recv_po_time_idx")],
			},
		),
	]
