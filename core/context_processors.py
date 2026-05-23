def cart_item_count(request):
    cart_id = request.session.get("cart_id")
    if not cart_id:
        return {"cart_item_count": 0}
    try:
        from django.db.models import Sum
        from cart.models import CartItem
        total = CartItem.objects.filter(cart_id=cart_id).aggregate(t=Sum("quantity"))["t"] or 0
    except Exception:
        total = 0
    return {"cart_item_count": total}


def branding(_request):
    return {
        "brand": {
            "name": "Popcorn_N_Such",
            "colors": {
                "red": "#D62828",
                "gold": "#F9B233",
                "cream": "#FFF3D6",
                "black": "#1F1F1F",
                "green": "#2E7D32",
            },
        }
    }


def staff_nav(request):
    """
    Staff/admin navigation + badge counts for the internal portal sidebar.
    Keep queries lightweight.
    """
    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        return {"staff_nav": {"enabled": False, "items": []}}

    is_staffish = bool(
        getattr(user, "is_superuser", False)
        or getattr(user, "is_staff", False)
        or (hasattr(user, "has_any_role") and user.has_any_role("staff", "admin"))
    )
    if not is_staffish:
        return {"staff_nav": {"enabled": False, "items": []}}

    can_create_users = bool(
        getattr(user, "is_superuser", False)
        or (hasattr(user, "has_role") and user.has_role("admin"))
    )
    site_ops_section = "Site Operations"

    low_sku = 0
    low_supplies = 0
    open_orders = 0
    try:
        from django.db.models import F
        from orders.models import Order, OrderStatus
        from products.models import SKU
        from supplies.models import Supply

        low_sku = SKU.objects.low_stock().count()
        low_supplies = Supply.objects.filter(is_active=True, inventory_quantity__lte=F("low_stock_threshold")).count()
        open_orders = Order.objects.filter(status__in=[OrderStatus.PAID, OrderStatus.PROCESSING, OrderStatus.PACKED]).count()
    except Exception:
        pass

    items = [
        {"section": "Dashboard", "label": "Portal Home", "url": "/dashboard/portal/"},
        {"section": "Dashboard", "label": "Owner Dashboard", "url": "/dashboard/owner/"},
        {"section": "Dashboard", "label": "Fulfillment", "url": "/dashboard/fulfillment/"},

        {"section": "Orders", "label": "All Orders", "url": "/orders/staff/", "badge": open_orders, "badge_variant": "primary"},
        {"section": "Orders", "label": "Shipping Labels", "url": "/shipping/labels/"},

        {"section": "Catalog", "label": "Products", "url": "/products/admin/products/"},
        {"section": "Catalog", "label": "SKU Management", "url": "/products/admin/skus/", "badge": low_sku, "badge_variant": "warning"},
        {"section": "Catalog", "label": "Coupons", "url": "/coupons/admin/"},
        {"section": "Catalog", "label": "Suppliers", "url": "/suppliers/"},
        {"section": "Catalog", "label": "Reorder Suggestions", "url": "/purchase-orders/reorder-suggestions/", "badge": low_supplies, "badge_variant": "warning"},

        {"section": site_ops_section, "label": "Site Configuration", "url": "/site-config/"},
        {"section": site_ops_section, "label": "Operational Settings", "url": "/dashboard/portal/operational-settings/"},
        {"section": site_ops_section, "label": "Staff How-To", "url": "/dashboard/portal/how-to/"},
        *(
            [{"section": site_ops_section, "label": "Create User", "url": "/accounts/staff/create-user/"}]
            if can_create_users
            else []
        ),

        {"section": "CRM", "label": "CRM Contacts", "url": "/crm/"},
        {"section": "CRM", "label": "Organizations", "url": "/organizations/crm/"},

        {"section": "Fundraising", "label": "Campaign Queue", "url": "/fundraisers/staff/queue/"},
        {"section": "Fundraising", "label": "Teams", "url": "/teams/staff/teams/"},
        {"section": "Fundraising", "label": "Seller Stores", "url": "/store/staff/stores/"},
        {"section": "Fundraising", "label": "Leaderboards", "url": "/leaderboards/staff/"},

        {"section": "Reports", "label": "Reports", "url": "/reports/"},
        {"section": "Reports", "label": "Alerts", "url": "/notifications/center/"},
    ]

    return {"staff_nav": {"enabled": True, "items": items}}
