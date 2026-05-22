from django.db import migrations


def seed_product_categories(apps, schema_editor):
    ProductCategory = apps.get_model("products", "ProductCategory")
    categories = [
        ("classic", "Classic"),
        ("sweet", "Sweet"),
        ("savory", "Savory"),
        ("signature", "Signature"),
        ("seasonal", "Seasonal"),
        ("gift-box", "Gift Box"),
        ("bundle", "Bundle"),
    ]

    for key, name in categories:
        ProductCategory.objects.get_or_create(key=key, defaults={"name": name, "is_active": True})


def unseed_product_categories(apps, schema_editor):
    ProductCategory = apps.get_model("products", "ProductCategory")
    ProductCategory.objects.filter(key__in=["classic", "sweet", "savory", "signature", "seasonal", "gift-box", "bundle"]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0002_productcategory_alter_product_category"),
    ]

    operations = [
        migrations.RunPython(seed_product_categories, unseed_product_categories),
    ]
