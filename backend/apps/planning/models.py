"""Account-owned planning settings: stations and build rules. Plans (step 3) will live here."""

from django.conf import settings
from django.db import models


class StationSource(models.TextChoices):
    DISCOVERED = "discovered", "Found from your jobs and assets"
    MANUAL = "manual", "Added by you"


class Station(models.Model):
    """A place the account builds at. Hull, name and system come from ESI where it can see
    them; rigs and tax cannot be read for structures the corp does not own, so they are set
    here. `location_id` is the structure or NPC station id (null for a hypothetical one)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="stations"
    )
    name = models.CharField(max_length=200)
    location_id = models.BigIntegerField(null=True, blank=True)
    system_id = models.IntegerField()
    structure_type_id = models.IntegerField(null=True, blank=True)  # null: NPC station
    rig_type_ids = models.JSONField(default=list, blank=True)
    activities = models.JSONField(default=list, blank=True)  # engine Activity values
    facility_tax = models.FloatField(default=0.0)  # percent
    tax_confirmed = models.BooleanField(default=False)
    enabled = models.BooleanField(default=True)
    source = models.CharField(max_length=16, choices=StationSource.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "planning_station"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "location_id"],
                condition=models.Q(location_id__isnull=False),
                name="planning_station_user_location_uniq",
            )
        ]
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class BuildRules(models.Model):
    """Account defaults; plans will override them (step 3)."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        primary_key=True,
        on_delete=models.CASCADE,
        related_name="build_rules",
    )
    item_blacklist = models.JSONField(default=list, blank=True)  # type ids always bought
    buy_categories = models.JSONField(default=list, blank=True)  # engine BuildCategory values
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "planning_build_rules"


class Visibility(models.TextChoices):
    PRIVATE = "private", "Only me"
    CORP = "corp", "My corporation"
    LINK = "link", "Anyone with the link"


class Plan(models.Model):
    """A named set of lines to build, with its own settings. Sharing (visibility) is stored
    now and enforced in step 7.

    Build rule overrides flip the account defaults for this plan only:
    `blacklist_add` / `blacklist_remove` are type ids; `category_overrides` maps an engine
    BuildCategory to "buy" or "build".

    Assets: `station_ids` limits where the plan builds (empty: every enabled account
    station). The asset filter defaults to the locations of those stations;
    `extra_location_ids` adds others, and `hangar_flags` (e.g. ["CorpSAG2", "Hangar"])
    limits which hangars count (empty: all)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="plans"
    )
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=False)
    activated_at = models.DateTimeField(null=True, blank=True)
    reserve_assets = models.BooleanField(default=False)
    priority = models.IntegerField(default=100)  # lower claims first
    visibility = models.CharField(
        max_length=16, choices=Visibility.choices, default=Visibility.PRIVATE
    )
    blacklist_add = models.JSONField(default=list, blank=True)
    blacklist_remove = models.JSONField(default=list, blank=True)
    category_overrides = models.JSONField(default=dict, blank=True)
    choices = models.JSONField(default=dict, blank=True)  # bp id -> {me, te, decryptor}
    station_ids = models.JSONField(default=list, blank=True)
    extra_location_ids = models.JSONField(default=list, blank=True)
    hangar_flags = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "planning_plan"
        ordering = ["priority", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(is_active=True),
                name="planning_plan_one_active_per_user",
            )
        ]

    def __str__(self) -> str:
        return self.name


class PlanLine(models.Model):
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="lines")
    type_id = models.IntegerField()
    quantity = models.PositiveIntegerField()
    position = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "planning_plan_line"
        ordering = ["position", "id"]
