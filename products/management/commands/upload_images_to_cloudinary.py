"""
Management command: upload_images_to_cloudinary

Re-uploads product images from local media/ storage to Cloudinary.
Run this once after setting CLOUDINARY_URL in your environment.

Usage:
    python manage.py upload_images_to_cloudinary
    python manage.py upload_images_to_cloudinary --dry-run
"""

import os

from django.core.files import File
from django.core.management.base import BaseCommand

from products.models import Product


class Command(BaseCommand):
    help = "Re-upload local product images to Cloudinary"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be uploaded without making changes",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        products_with_images = Product.objects.exclude(image="").exclude(image=None)
        total = products_with_images.count()

        if total == 0:
            self.stdout.write("No products with images found.")
            return

        self.stdout.write(f"Found {total} product(s) with images.")

        uploaded = 0
        skipped = 0
        errors = 0

        for product in products_with_images:
            image_name = product.image.name  # e.g. "products/popcorn.jpeg"

            # If the name already looks like a Cloudinary public_id
            # (no file extension or starts with "http"), skip it.
            local_path = product.image.path if hasattr(product.image, "path") else None

            try:
                local_path = product.image.path
            except NotImplementedError:
                # Cloudinary storage raises NotImplementedError for .path
                self.stdout.write(
                    self.style.WARNING(
                        f"  SKIP  {product.name!r} — already on Cloudinary ({image_name})"
                    )
                )
                skipped += 1
                continue

            if not os.path.exists(local_path):
                self.stdout.write(
                    self.style.WARNING(
                        f"  SKIP  {product.name!r} — local file not found: {local_path}"
                    )
                )
                skipped += 1
                continue

            if dry_run:
                self.stdout.write(f"  DRY   {product.name!r} → would upload {local_path}")
                continue

            try:
                with open(local_path, "rb") as f:
                    django_file = File(f, name=os.path.basename(local_path))
                    product.image.save(os.path.basename(local_path), django_file, save=True)

                self.stdout.write(
                    self.style.SUCCESS(
                        f"  OK    {product.name!r} → {product.image.url}"
                    )
                )
                uploaded += 1
            except Exception as exc:
                self.stderr.write(
                    self.style.ERROR(f"  FAIL  {product.name!r} — {exc}")
                )
                errors += 1

        if not dry_run:
            self.stdout.write(
                f"\nDone: {uploaded} uploaded, {skipped} skipped, {errors} errors."
            )
