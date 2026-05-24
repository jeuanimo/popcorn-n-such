import csv
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Count, Exists, F, Min, OuterRef, ProtectedError, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import DetailView, ListView, TemplateView
from django.views.generic import CreateView, UpdateView, View

from core.security import RoleRequiredMixin

from .forms import ProductAdminForm, ProductSKUCSVUploadForm, SKUAdminForm, SKUInventoryForm
from .models import CSVImportBatch, Product, ProductCategory, SKU
from .services import ProductSKUCSVImportService


CSV_IMPORT_ROUTE = "products:csv-import"
PRODUCT_ADMIN_LIST_ROUTE = "products:admin-list"
SKU_MANAGEMENT_ROUTE = "products:sku-management"

def _annotate_stock_summary(qs):
	"""Attach stock summary fields used across product listing surfaces."""
	return qs.annotate(
		total_active_stock=Sum("skus__inventory_quantity", filter=Q(skus__is_active=True)),
		purchasable_sku_count=Count("skus", filter=Q(skus__is_active=True, skus__inventory_quantity__gt=0), distinct=True),
		low_stock_sku_count=Count("skus", filter=Q(skus__is_active=True, skus__inventory_quantity__gt=0, skus__inventory_quantity__lte=F("skus__low_stock_threshold")), distinct=True),
	)


_SORT_FIELDS = {
	"price_asc":  ("min_price", "name"),
	"price_desc": ("-min_price", "name"),
	"newest":     ("-created_at", "name"),
	"featured":   ("-is_featured", "name"),
}


def _apply_shop_filters(qs, get_params):
	qs = qs.annotate(min_price=Min("skus__retail_price"))

	try:
		if get_params.get("min_price"):
			qs = qs.filter(min_price__gte=Decimal(get_params["min_price"]))
	except InvalidOperation:
		pass
	try:
		if get_params.get("max_price"):
			qs = qs.filter(min_price__lte=Decimal(get_params["max_price"]))
	except InvalidOperation:
		pass

	if get_params.get("in_stock") == "1":
		has_stock = SKU.objects.filter(
			product=OuterRef("pk"), is_active=True, inventory_quantity__gt=0
		)
		qs = qs.filter(Exists(has_stock))

	sort = get_params.get("sort", "featured")
	return qs.order_by(*_SORT_FIELDS.get(sort, _SORT_FIELDS["featured"]))


def _shop_context(request, *, selected_category=None, page_title="Shop All Products"):
	return {
		"categories": ProductCategory.objects.filter(is_active=True),
		"page_title": page_title,
		"selected_category": selected_category,
		"current_sort": request.GET.get("sort", "featured"),
		"current_min_price": request.GET.get("min_price", ""),
		"current_max_price": request.GET.get("max_price", ""),
		"current_in_stock": request.GET.get("in_stock", ""),
	}


class ProductListView(ListView):
	model = Product
	template_name = "products/product_list.html"
	context_object_name = "products"
	paginate_by = 16

	def get_queryset(self):
		store_type = self.request.GET.get("store", "standalone")
		base = _annotate_stock_summary((
			Product.objects.fundraiser_store() if store_type == "fundraiser"
			else Product.objects.public_store()
		).prefetch_related("skus"))
		return _apply_shop_filters(base, self.request.GET)

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context.update(_shop_context(self.request, page_title="Shop All Products"))
		context["total_count"] = self.object_list.count()
		return context


class ProductCategoryView(ListView):
	model = Product
	template_name = "products/product_list.html"
	context_object_name = "products"
	paginate_by = 16

	def get_queryset(self):
		self.category = get_object_or_404(ProductCategory, key=self.kwargs["category_key"], is_active=True)
		base = _annotate_stock_summary(Product.objects.public_store().filter(category=self.category).prefetch_related("skus"))
		return _apply_shop_filters(base, self.request.GET)

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context.update(_shop_context(
			self.request,
			selected_category=self.category,
			page_title=f"{self.category.name} Popcorn",
		))
		context["total_count"] = self.object_list.count()
		return context


class ProductDetailView(DetailView):
	model = Product
	template_name = "products/product_detail.html"
	context_object_name = "product"
	slug_field = "slug"
	slug_url_kwarg = "slug"

	def get_queryset(self):
		return Product.objects.active().prefetch_related("skus")

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context["active_skus"] = self.object.skus.filter(is_active=True)
		context["related_products"] = (
			Product.objects.public_store()
			.filter(category=self.object.category)
			.exclude(id=self.object.id)
			.prefetch_related("skus")[:4]
		)
		return context


class AdminProductListView(RoleRequiredMixin, ListView):
	model = Product
	template_name = "products/admin_product_list.html"
	context_object_name = "products"
	allowed_roles = ("staff", "admin")

	def get_queryset(self):
		return Product.objects.all().prefetch_related("skus")


class ProductCreateView(RoleRequiredMixin, CreateView):
	model = Product
	form_class = ProductAdminForm
	template_name = "products/product_form.html"
	allowed_roles = ("staff", "admin")
	success_url = reverse_lazy(PRODUCT_ADMIN_LIST_ROUTE)

	def form_valid(self, form):
		response = super().form_valid(form)
		messages.success(self.request, "Product created successfully.")
		return response

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context["form_title"] = "Add Product"
		context["submit_label"] = "Create Product"
		return context


class ProductUpdateView(RoleRequiredMixin, UpdateView):
	model = Product
	form_class = ProductAdminForm
	template_name = "products/product_form.html"
	allowed_roles = ("staff", "admin")
	success_url = reverse_lazy(PRODUCT_ADMIN_LIST_ROUTE)

	def form_valid(self, form):
		response = super().form_valid(form)
		messages.success(self.request, "Product updated successfully.")
		return response

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context["form_title"] = f"Edit {self.object.name}"
		context["submit_label"] = "Save Changes"
		return context


class ProductDeleteView(RoleRequiredMixin, View):
	allowed_roles = ("staff", "admin")

	def post(self, request, *args, **kwargs):
		product = get_object_or_404(Product, pk=kwargs["pk"])
		product_name = product.name
		try:
			product.delete()
			messages.success(request, f"Removed {product_name}.")
		except ProtectedError:
			product.is_active = False
			product.save(update_fields=["is_active", "updated_at"])
			messages.success(request, f"Archived {product_name} because it has related SKUs.")
		return redirect(PRODUCT_ADMIN_LIST_ROUTE)


class SKUCreateView(RoleRequiredMixin, CreateView):
	model = SKU
	form_class = SKUAdminForm
	template_name = "products/sku_form.html"
	allowed_roles = ("staff", "admin")
	success_url = reverse_lazy(SKU_MANAGEMENT_ROUTE)

	def form_valid(self, form):
		response = super().form_valid(form)
		messages.success(self.request, f"SKU {self.object.sku_code} created.")
		return response

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context["form_title"] = "Add SKU"
		context["submit_label"] = "Create SKU"
		return context


class SKUUpdateView(RoleRequiredMixin, UpdateView):
	model = SKU
	form_class = SKUAdminForm
	template_name = "products/sku_form.html"
	allowed_roles = ("staff", "admin")
	success_url = reverse_lazy(SKU_MANAGEMENT_ROUTE)

	def form_valid(self, form):
		response = super().form_valid(form)
		messages.success(self.request, f"SKU {self.object.sku_code} updated.")
		return response

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context["form_title"] = f"Edit SKU: {self.object.sku_code}"
		context["submit_label"] = "Save Changes"
		return context


class SKUDeleteView(RoleRequiredMixin, View):
	allowed_roles = ("staff", "admin")

	def post(self, request, *args, **kwargs):
		sku = get_object_or_404(SKU, pk=kwargs["pk"])
		sku_code = sku.sku_code
		try:
			sku.delete()
			messages.success(request, f"SKU {sku_code} deleted.")
		except ProtectedError:
			messages.error(request, f"SKU {sku_code} cannot be deleted — it has associated orders.")
		return redirect(SKU_MANAGEMENT_ROUTE)


class SKUManagementView(RoleRequiredMixin, TemplateView):
	template_name = "products/sku_management.html"
	allowed_roles = ("staff", "admin")

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context["skus"] = SKU.objects.select_related("product").all()
		context["inventory_form"] = SKUInventoryForm()
		context["last_batch"] = CSVImportBatch.objects.order_by("-uploaded_at").first()
		return context

	def post(self, request, *args, **kwargs):
		sku = get_object_or_404(SKU, sku_code=kwargs["sku_code"])
		form = SKUInventoryForm(request.POST, instance=sku)
		if form.is_valid():
			form.save()
		return redirect("products:sku-management")


class SKUCSVExportView(RoleRequiredMixin, TemplateView):
	allowed_roles = ("staff", "admin")

	def get(self, request, *args, **kwargs):
		response = HttpResponse(content_type="text/csv")
		response["Content-Disposition"] = 'attachment; filename="sku_export.csv"'

		writer = csv.writer(response)
		writer.writerow(
			[
				"sku_code",
				"product_slug",
				"product_name",
				"size",
				"retail_price",
				"cost_price",
				"weight_ounces",
				"inventory_quantity",
				"low_stock_threshold",
				"is_active",
				"barcode_upc",
			]
		)

		for sku in SKU.objects.select_related("product").all():
			writer.writerow(
				[
					sku.sku_code,
					sku.product.slug,
					sku.product.name,
					sku.size,
					sku.retail_price,
					sku.cost_price,
					sku.weight_ounces,
					sku.inventory_quantity,
					sku.low_stock_threshold,
					sku.is_active,
					sku.barcode_upc,
				]
			)

		return response


class SKUCSVTemplateView(RoleRequiredMixin, View):
	"""Download a blank CSV template pre-filled with headers and two example rows."""
	allowed_roles = ("staff", "admin")

	EXAMPLE_ROWS = [
		[
			"PNS-CBUT-SM", "Classic Butter Popcorn", "kettle-corn", "Classic Butter",
			"4 oz bag", "Light and buttery classic popcorn",
			"2.50", "7.99", "100", "10", "4.00",
			"true", "true", "true", "",
		],
		[
			"PNS-CCHZ-LG", "Cheddar Cheese Popcorn", "cheese", "Sharp Cheddar",
			"8 oz bag", "Real cheddar cheese coating on every kernel",
			"3.25", "10.99", "50", "5", "8.00",
			"true", "true", "true", "https://example.com/cheddar.jpg",
		],
	]

	def get(self, request, *args, **kwargs):
		response = HttpResponse(content_type="text/csv")
		response["Content-Disposition"] = 'attachment; filename="sku_import_template.csv"'
		writer = csv.writer(response)
		writer.writerow([
			"sku", "product_name", "category", "flavor", "size", "description",
			"cost_price", "retail_price", "inventory_count", "low_stock_threshold",
			"weight_oz", "is_active", "fundraiser_eligible", "standalone_store_eligible",
			"image_url",
		])
		for row in self.EXAMPLE_ROWS:
			writer.writerow(row)
		return response


class ProductSKUCSVImportView(RoleRequiredMixin, TemplateView):
	template_name = "products/csv_import.html"
	allowed_roles = ("staff", "admin")

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context["upload_form"] = ProductSKUCSVUploadForm()
		context["preview_batch"] = None
		context["recent_batches"] = CSVImportBatch.objects.select_related("uploader").all()[:10]
		return context

	def post(self, request, *args, **kwargs):
		action = request.POST.get("action", "preview")
		context = self.get_context_data()

		if action == "preview":
			form = ProductSKUCSVUploadForm(request.POST, request.FILES)
			context["upload_form"] = form
			if not form.is_valid():
				return self.render_to_response(context)

			batch = ProductSKUCSVImportService.preview_import(
				csv_file=form.cleaned_data["csv_file"],
				uploader=request.user,
				request=request,
			)
			context["preview_batch"] = batch
			context["row_errors"] = batch.row_errors.all()
			context["preview_rows"] = batch.preview_payload
			return self.render_to_response(context)

		if action == "commit":
			batch_id = request.POST.get("batch_id")
			batch = get_object_or_404(CSVImportBatch, id=batch_id)
			try:
				ProductSKUCSVImportService.commit_import(batch=batch, actor=request.user, request=request)
				messages.success(request, "CSV import committed successfully.")
			except ValidationError as exc:
				messages.error(request, str(exc))
				try:
					from notifications.alerts import NotificationService
					from notifications.models import StaffAlertEventType

					NotificationService.emit_event(
						event_type=StaffAlertEventType.CSV_IMPORT_FAILED,
						title=f"CSV import failed (batch #{batch.id})",
						message=str(exc),
						severity="warning",
						payload={"batch_id": batch.id, "error": str(exc)},
						dedupe_key=f"csv_failed:{batch.id}",
						actor=request.user,
						request=request,
					)
				except Exception:
					pass
			return redirect(CSV_IMPORT_ROUTE)

		if action == "rollback":
			try:
				batch = ProductSKUCSVImportService.rollback_last_import(actor=request.user, request=request)
				messages.success(request, f"Rolled back CSV import batch #{batch.id}.")
			except ValidationError as exc:
				messages.error(request, str(exc))
			return redirect(CSV_IMPORT_ROUTE)

		messages.error(request, "Unsupported CSV import action.")
		return redirect(CSV_IMPORT_ROUTE)
