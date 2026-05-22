import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def _default_token():
    return uuid.uuid4().hex


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("fundraisers", "0002_fundraisercampaign"),
        ("teams", "0003_alter_team_options_team_campaign_team_invite_code_and_more"),
        ("sellers", "0002_sellerstore"),
    ]

    operations = [
        migrations.CreateModel(
            name="ShareLink",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("token", models.CharField(db_index=True, default=_default_token, max_length=40, unique=True)),
                ("link_type", models.CharField(choices=[("campaign", "Campaign"), ("team", "Team"), ("seller", "Seller")], max_length=20)),
                ("click_count", models.PositiveIntegerField(default=0)),
                ("conversion_count", models.PositiveIntegerField(default=0)),
                ("last_clicked_at", models.DateTimeField(blank=True, null=True)),
                ("last_converted_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "campaign",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="share_links", to="fundraisers.fundraisercampaign"),
                ),
                (
                    "created_by",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_share_links", to=settings.AUTH_USER_MODEL),
                ),
                (
                    "seller_store",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="share_links", to="sellers.sellerstore"),
                ),
                (
                    "team",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="share_links", to="teams.team"),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="QRCode",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("image", models.ImageField(blank=True, upload_to="sharing/qr/%Y/%m/%d/")),
                ("format", models.CharField(default="png", max_length=20)),
                ("size", models.PositiveIntegerField(default=256)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "share_link",
                    models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="qr_code", to="sharing.sharelink"),
                ),
            ],
            options={
                "ordering": ["-updated_at"],
            },
        ),
        migrations.AddIndex(
            model_name="sharelink",
            index=models.Index(fields=["link_type", "created_at"], name="sharing_sha_link_ty_6971a1_idx"),
        ),
    ]
