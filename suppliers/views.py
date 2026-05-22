from __future__ import annotations

import csv
import io

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, render
from django.shortcuts import redirect
from django.views import View

from core.security import RoleRequiredMixin
from suppliers.models import Supplier
from suppliers.forms import SupplierCSVImportForm, SupplierForm


class SupplierListView(RoleRequiredMixin, View):
    allowed_roles = ("staff", "admin")
    template_name = "suppliers/list.html"

    def get(self, request):
        suppliers = Supplier.objects.all().order_by("name")
        return render(request, self.template_name, {"suppliers": suppliers})

    def post(self, request):
        delete_one_id = (request.POST.get("delete_one_id") or "").strip()
        action = (request.POST.get("action") or "").strip()
        if delete_one_id:
            deleted_count, _ = Supplier.objects.filter(id=delete_one_id).delete()
            if deleted_count:
                messages.success(request, "Supplier deleted.")
        elif action == "delete_selected":
            selected_ids = request.POST.getlist("supplier_ids")
            deleted_count = Supplier.objects.filter(id__in=selected_ids).count()
            Supplier.objects.filter(id__in=selected_ids).delete()
            messages.success(request, f"Deleted {deleted_count} supplier(s).")
        elif action == "delete_all":
            deleted_count = Supplier.objects.count()
            Supplier.objects.all().delete()
            messages.success(request, f"Deleted all suppliers ({deleted_count}).")
        return redirect("suppliers:list")


class SupplierDetailView(RoleRequiredMixin, View):
    allowed_roles = ("staff", "admin")
    template_name = "suppliers/detail.html"

    def get(self, request, supplier_id: int):
        supplier = get_object_or_404(Supplier, id=supplier_id)
        from purchase_orders.models import PurchaseOrder
        return render(
            request,
            self.template_name,
            {
                "supplier": supplier,
                "tasks": supplier.crm_tasks.select_related("assigned_to").all()[:50],
                "notes": supplier.crm_notes.select_related("created_by").all()[:50],
                "documents": supplier.documents.select_related("uploaded_by").all()[:20],
                "purchase_orders": supplier.purchase_orders.all()[:50],
                "purchase_orders_v2": PurchaseOrder.objects.filter(supplier=supplier).all()[:50],
                "performance_notes": supplier.performance_notes.select_related("created_by").all()[:50],
            },
        )


class SupplierCreateView(RoleRequiredMixin, View):
    allowed_roles = ("staff", "admin")
    template_name = "suppliers/form.html"

    def get(self, request):
        form = SupplierForm()
        return render(request, self.template_name, {"form": form, "form_title": "Add Supplier"})

    def post(self, request):
        form = SupplierForm(request.POST)
        if form.is_valid():
            supplier = form.save(commit=False)
            supplier.created_by = request.user
            supplier.save()
            messages.success(request, "Supplier created.")
            return redirect("suppliers:list")
        return render(request, self.template_name, {"form": form, "form_title": "Add Supplier"})


class SupplierUpdateView(RoleRequiredMixin, View):
    allowed_roles = ("staff", "admin")
    template_name = "suppliers/form.html"

    def get(self, request, supplier_id: int):
        supplier = get_object_or_404(Supplier, id=supplier_id)
        form = SupplierForm(instance=supplier)
        return render(request, self.template_name, {"form": form, "form_title": f"Edit {supplier.name}", "supplier": supplier})

    def post(self, request, supplier_id: int):
        supplier = get_object_or_404(Supplier, id=supplier_id)
        form = SupplierForm(request.POST, instance=supplier)
        if form.is_valid():
            form.save()
            messages.success(request, "Supplier updated.")
            return redirect("suppliers:list")
        return render(request, self.template_name, {"form": form, "form_title": f"Edit {supplier.name}", "supplier": supplier})


class SupplierDeleteView(RoleRequiredMixin, View):
    allowed_roles = ("staff", "admin")

    def post(self, request, supplier_id: int):
        supplier = get_object_or_404(Supplier, id=supplier_id)
        supplier.delete()
        messages.success(request, "Supplier deleted.")
        return redirect("suppliers:list")


class SupplierCSVImportView(RoleRequiredMixin, View):
    allowed_roles = ("staff", "admin")
    template_name = "suppliers/import_csv.html"

    FIELD_NAMES = [
        "name", "category", "status", "contact_person", "email", "phone", "website",
        "address_line_1", "address_line_2", "city", "state", "postal_code", "country",
        "products_supplies_provided", "payment_terms", "average_lead_time_days",
        "vendor_tax_id", "rating", "notes", "last_contact_date", "next_follow_up_date",
    ]

    def get(self, request):
        form = SupplierCSVImportForm()
        return render(request, self.template_name, {"form": form, "field_names": self.FIELD_NAMES})

    def post(self, request):
        form = SupplierCSVImportForm(request.POST, request.FILES)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form, "field_names": self.FIELD_NAMES})

        csv_file = form.cleaned_data["csv_file"]
        try:
            decoded = csv_file.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            messages.error(request, "CSV must be UTF-8 encoded.")
            return render(request, self.template_name, {"form": form, "field_names": self.FIELD_NAMES})

        reader = csv.DictReader(io.StringIO(decoded))
        if not reader.fieldnames:
            messages.error(request, "CSV is missing a header row.")
            return render(request, self.template_name, {"form": form, "field_names": self.FIELD_NAMES})

        created_count = 0
        updated_count = 0
        errors = []
        valid_rows = 0

        with transaction.atomic():
            for idx, row in enumerate(reader, start=2):
                name = (row.get("name") or "").strip()
                category = (row.get("category") or "").strip()
                if not name or not category:
                    errors.append(f"Row {idx}: name and category are required.")
                    continue

                data = {}
                for field in self.FIELD_NAMES:
                    if field in {"name", "category"}:
                        continue
                    value = (row.get(field) or "").strip()
                    if value == "":
                        continue
                    data[field] = value

                try:
                    supplier = Supplier.objects.filter(name=name).first()
                    if supplier:
                        supplier.name = name
                        supplier.category = category
                        for key, value in data.items():
                            setattr(supplier, key, value)
                        supplier.full_clean()
                        supplier.save()
                        updated_count += 1
                    else:
                        supplier = Supplier(name=name, category=category, created_by=request.user, **data)
                        supplier.full_clean()
                        supplier.save()
                        created_count += 1
                    valid_rows += 1
                except Exception as exc:
                    errors.append(f"Row {idx}: {exc}")

        if errors:
            for err in errors[:10]:
                messages.error(request, err)
            if len(errors) > 10:
                messages.error(request, f"...and {len(errors) - 10} more row errors.")

        messages.success(request, f"CSV processed. Created: {created_count}, Updated: {updated_count}, Valid rows: {valid_rows}.")
        return redirect("suppliers:list")
