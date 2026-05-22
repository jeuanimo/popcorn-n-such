from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View

from .models import CRMActivity, CRMContact, CRMNote, CRMRelationshipStatus, CRMTag, CRMTask, CRMTaskStatus


@method_decorator(staff_member_required, name="dispatch")
class CRMDashboardView(View):
    template_name = "crm/dashboard.html"

    def get(self, request):
        today = timezone.localdate()
        status_filter = request.GET.get("status", "")
        tag_filter = request.GET.get("tag", "")
        q = request.GET.get("q", "").strip()

        contacts = CRMContact.objects.filter(is_active=True).select_related("assigned_to")
        if status_filter:
            contacts = contacts.filter(relationship_status=status_filter)
        if tag_filter:
            contacts = contacts.filter(tag_links__tag__name=tag_filter)
        if q:
            contacts = contacts.filter(
                Q(display_name__icontains=q) | Q(email__icontains=q) | Q(phone__icontains=q)
            )
        contacts = contacts.order_by("display_name")[:100]

        overdue_tasks = (
            CRMTask.objects.filter(status=CRMTaskStatus.OPEN, due_date__lt=today)
            .select_related("contact", "assigned_to")
            .order_by("due_date")[:20]
        )
        due_today = (
            CRMTask.objects.filter(status=CRMTaskStatus.OPEN, due_date=today)
            .select_related("contact", "assigned_to")
            .order_by("contact__display_name")[:20]
        )
        recent_activity = (
            CRMActivity.objects.select_related("contact", "created_by").order_by("-occurred_at")[:15]
        )

        status_counts = {
            s.value: CRMContact.objects.filter(is_active=True, relationship_status=s.value).count()
            for s in CRMRelationshipStatus
        }
        status_filters = [
            {"value": value, "label": label, "count": status_counts.get(value, 0)}
            for value, label in CRMRelationshipStatus.choices
        ]
        tags = CRMTag.objects.annotate(contact_count=Count("contact_links")).order_by("name")

        context = {
            "contacts": contacts,
            "overdue_tasks": overdue_tasks,
            "due_today": due_today,
            "recent_activity": recent_activity,
            "status_choices": CRMRelationshipStatus.choices,
            "status_counts": status_counts,
            "status_filters": status_filters,
            "tags": tags,
            "selected_status": status_filter,
            "selected_tag": tag_filter,
            "q": q,
            "today": today,
        }
        return render(request, self.template_name, context)


@method_decorator(staff_member_required, name="dispatch")
class CRMContactDetailView(View):
    template_name = "crm/contact_detail.html"

    def get(self, request, pk):
        contact = get_object_or_404(CRMContact, pk=pk)
        notes = contact.crm_notes.select_related("created_by").order_by("-created_at")
        tasks = contact.crm_tasks.select_related("assigned_to").order_by("status", "due_date")
        activities = contact.activities.select_related("created_by").order_by("-occurred_at")[:30]
        return render(request, self.template_name, {
            "contact": contact,
            "notes": notes,
            "tasks": tasks,
            "activities": activities,
            "status_choices": CRMRelationshipStatus.choices,
            "task_status_choices": CRMTaskStatus.choices,
        })

    def post(self, request, pk):
        contact = get_object_or_404(CRMContact, pk=pk)
        action = request.POST.get("action", "")

        if action == "add_note":
            note_text = request.POST.get("note", "").strip()
            if note_text:
                CRMNote.objects.create(contact=contact, note=note_text, created_by=request.user)
                CRMActivity.objects.create(
                    contact=contact,
                    activity_type="note",
                    summary="Note added",
                    created_by=request.user,
                )
        elif action == "add_task":
            title = request.POST.get("title", "").strip()
            due_date = request.POST.get("due_date") or None
            if title:
                CRMTask.objects.create(
                    contact=contact,
                    title=title,
                    due_date=due_date,
                    assigned_to=request.user,
                    created_by=request.user,
                )
        elif action == "update_status":
            new_status = request.POST.get("relationship_status", "")
            if new_status in CRMRelationshipStatus.values:
                old_status = contact.relationship_status
                contact.relationship_status = new_status
                contact.save(update_fields=["relationship_status", "updated_at"])
                CRMActivity.objects.create(
                    contact=contact,
                    activity_type="status_change",
                    summary=f"Status changed from {old_status} to {new_status}",
                    created_by=request.user,
                )
        elif action == "close_task":
            task_id = request.POST.get("task_id")
            CRMTask.objects.filter(pk=task_id, contact=contact).update(status=CRMTaskStatus.COMPLETED)

        return redirect("crm:contact-detail", pk=pk)


@method_decorator(staff_member_required, name="dispatch")
class CRMContactCreateView(View):
    template_name = "crm/contact_form.html"

    def get(self, request):
        return render(request, self.template_name, {"status_choices": CRMRelationshipStatus.choices})

    def post(self, request):
        display_name = request.POST.get("display_name", "").strip()
        if not display_name:
            return render(request, self.template_name, {
                "status_choices": CRMRelationshipStatus.choices,
                "error": "Display name is required.",
                "data": request.POST,
            })
        contact = CRMContact.objects.create(
            display_name=display_name,
            email=request.POST.get("email", "").strip(),
            phone=request.POST.get("phone", "").strip(),
            relationship_status=request.POST.get("relationship_status", CRMRelationshipStatus.LEAD),
            notes=request.POST.get("notes", "").strip(),
            assigned_to=request.user,
            created_by=request.user,
        )
        CRMActivity.objects.create(
            contact=contact,
            activity_type="created",
            summary="Contact created",
            created_by=request.user,
        )
        return redirect("crm:contact-detail", pk=contact.pk)
