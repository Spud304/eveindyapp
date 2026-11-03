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
