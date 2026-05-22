from django import template

from core.models import SiteContentBlock

register = template.Library()


@register.inclusion_tag("core/_managed_content_blocks.html")
def render_managed_content(page_key: str):
    blocks = SiteContentBlock.objects.filter(page_key=page_key, is_active=True).order_by("sort_order", "id")
    return {"managed_blocks": blocks}
