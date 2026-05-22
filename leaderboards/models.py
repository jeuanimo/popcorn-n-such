from django.conf import settings
from django.db import models


class LeaderboardScope(models.TextChoices):
    CAMPAIGN_SELLERS = "campaign_sellers", "Top Sellers in Campaign"
    CAMPAIGN_TEAMS = "campaign_teams", "Top Teams in Campaign"
    TEAM_SELLERS = "team_sellers", "Top Sellers in Team"
    ALL_CAMPAIGNS = "all_campaigns", "Top Campaigns (Staff)"


class LeaderboardSnapshot(models.Model):
    """
    Cached leaderboard rows, refreshed after each paid order.
    One row per scope+campaign/team combination and per ranked entity.
    """

    scope = models.CharField(max_length=30, choices=LeaderboardScope.choices)

    # Scope anchors (at most one is set)
    campaign = models.ForeignKey(
        "fundraisers.FundraiserCampaign",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="leaderboard_rows",
    )
    team = models.ForeignKey(
        "teams.Team",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="leaderboard_rows",
    )

    # Ranked entity identifiers (only one set per row)
    seller_store = models.ForeignKey(
        "sellers.SellerStore",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="leaderboard_rows",
    )
    ranked_team = models.ForeignKey(
        "teams.Team",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="ranked_leaderboard_rows",
    )
    ranked_campaign = models.ForeignKey(
        "fundraisers.FundraiserCampaign",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="ranked_leaderboard_rows",
    )

    # Display identity (safe public name — no private customer data)
    display_name = models.CharField(max_length=200)

    # Metrics
    rank = models.PositiveIntegerField()
    total_sales_cents = models.PositiveIntegerField(default=0)
    total_orders = models.PositiveIntegerField(default=0)
    total_units = models.PositiveIntegerField(default=0)
    goal_cents = models.PositiveIntegerField(default=0)
    goal_progress_percent = models.PositiveSmallIntegerField(default=0)

    refreshed_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["scope", "campaign", "team", "rank"]
        indexes = [
            models.Index(fields=["scope", "campaign"]),
            models.Index(fields=["scope", "team"]),
        ]

    def __str__(self) -> str:
        return f"[{self.get_scope_display()}] #{self.rank} {self.display_name}"


class LeaderboardSettings(models.Model):
    """
    Per-campaign leaderboard visibility / configuration.
    Staff can hide public leaderboards here.
    """

    campaign = models.OneToOneField(
        "fundraisers.FundraiserCampaign",
        on_delete=models.CASCADE,
        related_name="leaderboard_settings",
    )
    public_sellers_visible = models.BooleanField(
        default=True,
        help_text="Show top-seller leaderboard on the public campaign page.",
    )
    public_teams_visible = models.BooleanField(
        default=True,
        help_text="Show top-team leaderboard on the public campaign page.",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Leaderboard settings for {self.campaign}"
