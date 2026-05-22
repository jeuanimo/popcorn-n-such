from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("cart", "0002_cartattribution_seller_store"),
        ("fundraisers", "0002_fundraisercampaign"),
        ("teams", "0003_alter_team_options_team_campaign_team_invite_code_and_more"),
        ("sharing", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="cartattribution",
            name="campaign",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="cart_attributions",
                to="fundraisers.fundraisercampaign",
            ),
        ),
        migrations.AddField(
            model_name="cartattribution",
            name="team_ref",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="cart_attributions",
                to="teams.team",
            ),
        ),
        migrations.AddField(
            model_name="cartattribution",
            name="share_link",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="cart_attributions",
                to="sharing.sharelink",
            ),
        ),
    ]
