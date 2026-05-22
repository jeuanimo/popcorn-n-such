from django.db import migrations, models


class Migration(migrations.Migration):

	initial = True

	dependencies = []

	operations = [
		migrations.CreateModel(
			name="Supply",
			fields=[
				("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
				("name", models.CharField(max_length=200, unique=True)),
				("sku_code", models.CharField(blank=True, help_text="Internal supply SKU/code (optional).", max_length=60)),
				(
					"category",
					models.CharField(
						choices=[
							("ingredient", "Ingredient"),
							("packaging", "Packaging"),
							("shipping_supply", "Shipping supply"),
							("equipment", "Equipment"),
							("other", "Other"),
						],
						default="other",
						max_length=30,
					),
				),
				("unit", models.CharField(default="each", help_text="e.g. each, lb, oz, case", max_length=30)),
				("inventory_quantity", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
				("low_stock_threshold", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
				("is_active", models.BooleanField(default=True)),
				("notes", models.TextField(blank=True)),
				("created_at", models.DateTimeField(auto_now_add=True)),
				("updated_at", models.DateTimeField(auto_now=True)),
			],
			options={
				"ordering": ["name"],
				"indexes": [
					models.Index(fields=["category", "is_active"], name="supplies_sup_category_1d9ec7_idx"),
				],
			},
		),
	]

