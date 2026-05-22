from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from core.security import role_required
from .models import UserRole
from .admin_user_creation_form import AdminUserCreationForm

@login_required
def admin_user_create_view(request):
    if not request.user.has_role(UserRole.ADMIN):
        messages.error(request, "You do not have permission to create users.")
        return redirect("accounts:staff-console")

    if request.method == "POST":
        form = AdminUserCreationForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "User account created successfully.")
            return redirect("accounts:staff-console")
    else:
        form = AdminUserCreationForm()
    return render(request, "accounts/admin_user_create.html", {"form": form})
