from uuid import uuid4

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from accounts.models import Role, User, UserRole

from .models import CSVImportBatch, CSVImportBatchStatus, Product, ProductCategory, SKU


TEST_PASSWORD = f"test-{uuid4()}"


class ProductVisibilityTests(TestCase):
	def setUp(self):
		self.classic, _ = ProductCategory.objects.get_or_create(key="classic", defaults={"name": "Classic"})
		self.seasonal, _ = ProductCategory.objects.get_or_create(key="seasonal", defaults={"name": "Seasonal"})
		self.signature, _ = ProductCategory.objects.get_or_create(key="signature", defaults={"name": "Signature"})

		self.active_product = Product.objects.create(
			name="Classic Butter Popcorn",
			slug="classic-butter",
			description="A customer favorite.",
			category=self.classic,
			flavor="Butter",
			is_active=True,
			standalone_store_eligible=True,
			fundraiser_eligible=True,
		)
		self.inactive_product = Product.objects.create(
			name="Hidden Product",
			slug="hidden-product",
			description="Should not show publicly.",
			category=self.seasonal,
			flavor="Pumpkin",
			is_active=False,
			standalone_store_eligible=True,
			fundraiser_eligible=True,
		)

	def test_inactive_product_not_in_public_store(self):
		response = self.client.get(reverse("products:list"))
		self.assertContains(response, "Classic Butter Popcorn")
		self.assertNotContains(response, "Hidden Product")

	def test_fundraiser_store_hides_ineligible_products(self):
		Product.objects.create(
			name="Standalone Only",
			slug="standalone-only",
			description="Not for fundraiser.",
			category=self.signature,
			flavor="Caramel",
			is_active=True,
			standalone_store_eligible=True,
			fundraiser_eligible=False,
		)
		response = self.client.get(reverse("products:list"), {"store": "fundraiser"})
		self.assertContains(response, "Classic Butter Popcorn")
		self.assertNotContains(response, "Standalone Only")


class SKUBusinessRuleTests(TestCase):
	def setUp(self):
		self.savory, _ = ProductCategory.objects.get_or_create(key="savory", defaults={"name": "Savory"})
		self.product = Product.objects.create(
			name="Cheddar Popcorn",
			slug="cheddar-popcorn",
			description="Savory and bold.",
			category=self.savory,
			flavor="Cheddar",
			is_active=True,
			standalone_store_eligible=True,
			fundraiser_eligible=True,
		)

	def test_inactive_sku_is_not_purchasable(self):
		sku = SKU.objects.create(
			sku_code="CHED-LG",
			product=self.product,
			size="Large",
			retail_price="12.99",
			cost_price="6.00",
			weight_ounces="14.00",
			inventory_quantity=10,
			low_stock_threshold=3,
			is_active=False,
		)
		self.assertFalse(sku.is_purchasable)

	def test_inventory_decreases_only_after_payment_confirmation(self):
		sku = SKU.objects.create(
			sku_code="CHED-SM",
			product=self.product,
			size="Small",
			retail_price="8.99",
			cost_price="3.50",
			weight_ounces="8.00",
			inventory_quantity=5,
			low_stock_threshold=2,
			is_active=True,
		)

		with self.assertRaisesMessage(ValidationError, "Inventory can only be reduced after payment confirmation"):
			sku.decrease_inventory(1, payment_confirmed=False)

		sku.decrease_inventory(2, payment_confirmed=True)
		sku.refresh_from_db()
		self.assertEqual(sku.inventory_quantity, 3)


class ProductSKUCSVImportTests(TestCase):
	def setUp(self):
		self.staff_role, _ = Role.objects.get_or_create(key=UserRole.STAFF)
		self.staff_user = User.objects.create_user(
			username="staff_csv",
			password=TEST_PASSWORD,
			is_staff=True,
		)
		self.staff_user.roles.add(self.staff_role)

		self.category, _ = ProductCategory.objects.get_or_create(key="classic", defaults={"name": "Classic"})
		self.product = Product.objects.create(
			name="Legacy Product",
			slug="legacy-product",
			description="Legacy",
			category=self.category,
			flavor="Butter",
			is_active=True,
			fundraiser_eligible=True,
			standalone_store_eligible=True,
		)
		self.existing_sku = SKU.objects.create(
			sku_code="EXIST-001",
			product=self.product,
			size="Small",
			retail_price="5.00",
			cost_price="2.00",
			weight_ounces="3.00",
			inventory_quantity=5,
			low_stock_threshold=1,
			is_active=True,
		)

	def _csv_file(self, content: str, name: str = "products.csv", content_type: str = "text/csv"):
		return SimpleUploadedFile(name=name, content=content.encode("utf-8"), content_type=content_type)

	def test_preview_shows_row_level_errors(self):
		self.client.login(username="staff_csv", password=TEST_PASSWORD)
		csv_payload = (
			"sku,product_name,category,flavor,size,description,cost_price,retail_price,inventory_count,low_stock_threshold,weight_oz,is_active,fundraiser_eligible,standalone_store_eligible,image_url\n"
			"DUP-1,Cheddar Pop,Savory,Cheddar,Small,Good,2.00,5.00,12,3,4.00,true,true,true,\n"
			"DUP-1,Cheddar Pop,Savory,Cheddar,Large,Good,abc,7.00,8,2,6.00,true,true,true,\n"
		)

		response = self.client.post(
			reverse("products:csv-import"),
			{"action": "preview", "csv_file": self._csv_file(csv_payload)},
		)

		self.assertEqual(response.status_code, 200)
		batch = CSVImportBatch.objects.latest("id")
		self.assertEqual(batch.status, CSVImportBatchStatus.PREVIEWED)
		self.assertEqual(batch.invalid_rows, 1)
		self.assertContains(response, "Duplicate SKU within uploaded CSV")

	def test_commit_creates_and_updates_skus(self):
		self.client.login(username="staff_csv", password=TEST_PASSWORD)
		csv_payload = (
			"sku,product_name,category,flavor,size,description,cost_price,retail_price,inventory_count,low_stock_threshold,weight_oz,is_active,fundraiser_eligible,standalone_store_eligible,image_url\n"
			"EXIST-001,Legacy Product,Classic,Butter,Medium,Updated item,2.50,6.00,20,4,5.50,true,true,true,\n"
			"NEW-001,Caramel Crunch,Sweet,Caramel,Large,New item,3.00,8.50,30,5,7.00,true,true,true,\n"
		)

		preview_response = self.client.post(
			reverse("products:csv-import"),
			{"action": "preview", "csv_file": self._csv_file(csv_payload)},
		)
		self.assertEqual(preview_response.status_code, 200)

		batch = CSVImportBatch.objects.latest("id")
		self.assertEqual(batch.invalid_rows, 0)

		commit_response = self.client.post(
			reverse("products:csv-import"),
			{"action": "commit", "batch_id": str(batch.id)},
			follow=True,
		)
		self.assertEqual(commit_response.status_code, 200)

		batch.refresh_from_db()
		self.assertEqual(batch.status, CSVImportBatchStatus.COMMITTED)
		self.assertEqual(batch.created_skus, 1)
		self.assertEqual(batch.updated_skus, 1)

		self.existing_sku.refresh_from_db()
		self.assertEqual(self.existing_sku.size, "Medium")
		self.assertEqual(self.existing_sku.inventory_quantity, 20)
		self.assertTrue(SKU.objects.filter(sku_code="NEW-001").exists())

	def test_rollback_last_import(self):
		self.client.login(username="staff_csv", password=TEST_PASSWORD)
		csv_payload = (
			"sku,product_name,category,flavor,size,description,cost_price,retail_price,inventory_count,low_stock_threshold,weight_oz,is_active,fundraiser_eligible,standalone_store_eligible,image_url\n"
			"EXIST-001,Legacy Product,Classic,Butter,XL,Updated item,2.20,5.90,15,2,4.50,true,true,true,\n"
		)

		self.client.post(
			reverse("products:csv-import"),
			{"action": "preview", "csv_file": self._csv_file(csv_payload)},
		)
		batch = CSVImportBatch.objects.latest("id")
		self.client.post(reverse("products:csv-import"), {"action": "commit", "batch_id": str(batch.id)})

		self.existing_sku.refresh_from_db()
		self.assertEqual(self.existing_sku.size, "XL")

		rollback_response = self.client.post(reverse("products:csv-import"), {"action": "rollback"}, follow=True)
		self.assertEqual(rollback_response.status_code, 200)

		batch.refresh_from_db()
		self.assertEqual(batch.status, CSVImportBatchStatus.ROLLED_BACK)
		self.existing_sku.refresh_from_db()
		self.assertEqual(self.existing_sku.size, "Small")


class ProductAdminManagementTests(TestCase):
	def setUp(self):
		self.staff_role, _ = Role.objects.get_or_create(key=UserRole.STAFF)
		self.staff_user = User.objects.create_user(
			username="staff_manager",
			password=TEST_PASSWORD,
			is_staff=True,
		)
		self.staff_user.roles.add(self.staff_role)
		self.category, _ = ProductCategory.objects.get_or_create(key="classic", defaults={"name": "Classic"})
		self.product = Product.objects.create(
			name="Movie Butter",
			slug="movie-butter",
			description="Original item.",
			category=self.category,
			flavor="Butter",
		)

	def test_staff_can_create_product(self):
		self.client.login(username="staff_manager", password=TEST_PASSWORD)
		response = self.client.post(
			reverse("products:admin-create"),
			{
				"name": "Caramel Blast",
				"slug": "caramel-blast",
				"description": "Sweet and crunchy.",
				"category": self.category.id,
				"flavor": "Caramel",
				"external_image_url": "",
				"is_active": "on",
				"is_featured": "on",
				"fundraiser_eligible": "on",
				"standalone_store_eligible": "on",
			},
			follow=True,
		)

		self.assertEqual(response.status_code, 200)
		self.assertTrue(Product.objects.filter(slug="caramel-blast").exists())
		self.assertContains(response, "Product created successfully.")

	def test_staff_can_edit_product(self):
		self.client.login(username="staff_manager", password=TEST_PASSWORD)
		response = self.client.post(
			reverse("products:admin-edit", args=[self.product.id]),
			{
				"name": "Movie Butter Deluxe",
				"slug": "movie-butter",
				"description": "Updated item.",
				"category": self.category.id,
				"flavor": "Butter",
				"external_image_url": "",
				"is_active": "on",
				"fundraiser_eligible": "on",
				"standalone_store_eligible": "on",
			},
			follow=True,
		)

		self.assertEqual(response.status_code, 200)
		self.product.refresh_from_db()
		self.assertEqual(self.product.name, "Movie Butter Deluxe")
		self.assertContains(response, "Product updated successfully.")

	def test_remove_archives_product_with_skus(self):
		SKU.objects.create(
			sku_code="MOVIE-SM",
			product=self.product,
			size="Small",
			retail_price="5.00",
			cost_price="2.00",
			weight_ounces="3.00",
			inventory_quantity=10,
			low_stock_threshold=2,
		)
		self.client.login(username="staff_manager", password=TEST_PASSWORD)
		response = self.client.post(reverse("products:admin-delete", args=[self.product.id]), follow=True)

		self.assertEqual(response.status_code, 200)
		self.product.refresh_from_db()
		self.assertFalse(self.product.is_active)
		self.assertContains(response, "Archived Movie Butter because it has related SKUs.")
