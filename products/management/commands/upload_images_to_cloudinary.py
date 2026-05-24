"""
Management command: upload_images_to_cloudinary

Uploads product images from your LOCAL media/ folder to Cloudinary.
Run this on your local machine (not on Render) where the files exist.

Usage:
    CLOUDINARY_URL=cloudinary://KEY:SECRET@CLOUD python manage.py upload_images_to_cloudinary
    CLOUDINARY_URL=... python manage.py upload_images_to_cloudinary --dry-run
"""

from pathlib import Path

import cloudinary.uploader
from django.conf import settings
from django.core.management.base import BaseCommand

from products.models import Product


class Command(BaseCommand):
    help = "Upload product images from local media/ to Cloudinary"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be uploaded without making changes",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        products = Product.objects.exclude(image="").exclude(image=None)
        total = products.count()

        if total == 0:
            self.stdout.write("No products with images found.")
            return

        self.stdout.write(f"Found {total} product(s) with images.")

        # Collect unique image names so we only upload each file once
        unique_names = {}
        for product in products:
            unique_names.setdefault(product.image.name, []).append(product)

        uploaded = 0
        skipped = 0
        errors = 0

        for name, product_list in unique_names.items():
            local_path = Path(settings.MEDIA_ROOT) / name

            if not local_path.exists():
                self.stdout.write(
                    self.style.WARNING(f"  SKIP  {name} — not found at {local_path}")
                )
                skipped += 1
                continue

            if dry_run:
                self.stdout.write(f"  DRY   would upload {local_path}")
                continue

            try:
                result = cloudinary.uploader.upload(
                    str(local_path),
                    public_id=name,
                    overwrite=True,
                    resource_type="image",
                )
                self.stdout.write(
                    self.style.SUCCESS(f"  OK    {name} → {result['url']}")
                )
                uploaded += 1
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"  FAIL  {name} — {exc}"))
                errors += 1

        if not dry_run:
            self.stdout.write(
                f"\nDone: {uploaded} uploaded, {skipped} skipped, {errors} errors."
            )
