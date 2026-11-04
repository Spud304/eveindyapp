"""Snapshots of ESI data per owner (a character or a corporation), plus public market data.

Assets and blueprints are replaced as a whole on each sync. Industry jobs are upserted by
job id and never deleted, because ESI drops completed jobs after a while and the tracker
(step 5) needs their history.

Corp data is fetched with a director's token and is private to accounts that have a
character holding the required role in that corp (see `access.py`).
"""

from django.db import models


class OwnerKind(models.TextChoices):
    CHARACTER = "character", "Character"
    CORPORATION = "corporation", "Corporation"


class Feed(models.TextChoices):
    SKILLS = "skills", "Skills"
    ROLES = "roles", "Corporation roles"
    ASSETS = "assets", "Assets"
    BLUEPRINTS = "blueprints", "Blueprints"
    JOBS = "jobs", "Industry jobs"
    DIVISIONS = "divisions", "Hangar divisions"


class FeedStatus(models.Model):
    """Last sync of one feed for one owner. For corp feeds, which character's token was used."""

    owner_kind = models.CharField(max_length=16, choices=OwnerKind.choices)
    owner_id = models.BigIntegerField()
    feed = models.CharField(max_length=16, choices=Feed.choices)
    source_character = models.ForeignKey(
        "accounts.EveCharacter", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    ok = models.BooleanField(default=False)
    error = models.CharField(max_length=300, blank=True)
    rows = models.IntegerField(default=0)
    attempted_at = models.DateTimeField()
    fetched_at = models.DateTimeField(null=True, blank=True)  # last success

    class Meta:
        db_table = "esidata_feed_status"
        constraints = [
            models.UniqueConstraint(
                fields=["owner_kind", "owner_id", "feed"], name="esidata_feed_status_uniq"
            )
        ]

    def __str__(self) -> str:
        return f"{self.owner_kind}:{self.owner_id} {self.feed} {'ok' if self.ok else 'error'}"


class Corporation(models.Model):
    id = models.BigIntegerField(primary_key=True)
    name = models.CharField(max_length=100, blank=True)
    ticker = models.CharField(max_length=10, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "esidata_corporation"

    def __str__(self) -> str:
        return self.name or str(self.id)


class CharacterSkill(models.Model):
    character = models.ForeignKey(
        "accounts.EveCharacter", on_delete=models.CASCADE, related_name="skills"
    )
    skill_id = models.IntegerField()
    active_level = models.SmallIntegerField()
    trained_level = models.SmallIntegerField()
    skillpoints = models.BigIntegerField()

    class Meta:
        db_table = "esidata_character_skill"
        constraints = [
            models.UniqueConstraint(fields=["character", "skill_id"], name="esidata_skill_uniq")
        ]


class CharacterRoles(models.Model):
    character = models.OneToOneField(
        "accounts.EveCharacter", primary_key=True, on_delete=models.CASCADE, related_name="roles"
    )
    corporation_id = models.BigIntegerField(null=True, blank=True)  # corp the roles were read in
    roles = models.JSONField(default=list)
    roles_at_hq = models.JSONField(default=list)
    roles_at_base = models.JSONField(default=list)
    roles_at_other = models.JSONField(default=list)

    class Meta:
        db_table = "esidata_character_roles"

    def has(self, *any_of: str) -> bool:
        return bool(set(any_of) & set(self.roles))


class Asset(models.Model):
    """One ESI asset row. `root_location_id` is the station, structure or solar system the
    item sits in after walking up through containers, ships and corp offices; `hangar_flag`
    is the flag of the item at the top of that chain (e.g. `Hangar`, `CorpSAG3`)."""

    owner_kind = models.CharField(max_length=16, choices=OwnerKind.choices)
    owner_id = models.BigIntegerField()
    item_id = models.BigIntegerField()
    type_id = models.IntegerField()
    quantity = models.BigIntegerField()
    location_id = models.BigIntegerField()
    location_type = models.CharField(max_length=16)
    location_flag = models.CharField(max_length=48)
    is_singleton = models.BooleanField(default=False)
    is_blueprint_copy = models.BooleanField(null=True, blank=True)
    root_location_id = models.BigIntegerField()
    hangar_flag = models.CharField(max_length=48)

    class Meta:
        db_table = "esidata_asset"
        constraints = [
            models.UniqueConstraint(
                fields=["owner_kind", "owner_id", "item_id"], name="esidata_asset_owner_item"
            )
        ]
        indexes = [
            models.Index(
                fields=["owner_kind", "owner_id", "type_id"], name="esidata_asset_owner_type"
            ),
            models.Index(fields=["root_location_id"], name="esidata_asset_root"),
        ]


class BlueprintItem(models.Model):
    """A blueprint an owner holds. ESI `quantity`: -1 original, -2 copy, N > 0 a stack of N
    unresearched originals. `runs` is -1 for originals."""

    owner_kind = models.CharField(max_length=16, choices=OwnerKind.choices)
    owner_id = models.BigIntegerField()
    item_id = models.BigIntegerField()
    type_id = models.IntegerField()
    location_id = models.BigIntegerField()
    location_flag = models.CharField(max_length=48)
    quantity = models.IntegerField()
    runs = models.IntegerField()
    material_efficiency = models.SmallIntegerField()
    time_efficiency = models.SmallIntegerField()
    root_location_id = models.BigIntegerField()
    hangar_flag = models.CharField(max_length=48)

    class Meta:
        db_table = "esidata_blueprint"
        constraints = [
            models.UniqueConstraint(
                fields=["owner_kind", "owner_id", "item_id"], name="esidata_bp_owner_item"
            )
        ]
        indexes = [
            models.Index(
                fields=["owner_kind", "owner_id", "type_id"], name="esidata_bp_owner_type"
            ),
        ]

    @property
    def is_copy(self) -> bool:
        return self.quantity == -2


class IndustryJob(models.Model):
    job_id = models.BigIntegerField(primary_key=True)
    owner_kind = models.CharField(max_length=16, choices=OwnerKind.choices)
    owner_id = models.BigIntegerField()
    installer_id = models.BigIntegerField()
    facility_id = models.BigIntegerField()
    location_id = models.BigIntegerField()  # character jobs: station_id; corp jobs: location_id
    activity_id = models.SmallIntegerField()
    blueprint_id = models.BigIntegerField()
    blueprint_type_id = models.IntegerField()
    blueprint_location_id = models.BigIntegerField()
    output_location_id = models.BigIntegerField()
    product_type_id = models.IntegerField(null=True, blank=True)
    runs = models.IntegerField()
    licensed_runs = models.IntegerField(null=True, blank=True)
    successful_runs = models.IntegerField(null=True, blank=True)
    probability = models.FloatField(null=True, blank=True)
    cost = models.FloatField(null=True, blank=True)
    status = models.CharField(max_length=16)
    duration = models.IntegerField()
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    pause_date = models.DateTimeField(null=True, blank=True)
    completed_date = models.DateTimeField(null=True, blank=True)
    completed_character_id = models.BigIntegerField(null=True, blank=True)
    last_seen_at = models.DateTimeField()

    class Meta:
        db_table = "esidata_industry_job"
        indexes = [
            models.Index(
                fields=["owner_kind", "owner_id", "status"], name="esidata_job_owner_status"
            ),
            models.Index(fields=["installer_id"], name="esidata_job_installer"),
        ]


class CorpDivision(models.Model):
    corporation = models.ForeignKey(Corporation, on_delete=models.CASCADE, related_name="divisions")
    division = models.SmallIntegerField()  # 1-7, CorpSAG<n>
    name = models.CharField(max_length=100, blank=True)

    class Meta:
        db_table = "esidata_corp_division"
        constraints = [
            models.UniqueConstraint(
                fields=["corporation", "division"], name="esidata_corp_division_uniq"
            )
        ]


class MarketPrice(models.Model):
    """CCP's /markets/prices: adjusted price (for EIV) and average price. Not a buy price."""

    type_id = models.IntegerField(primary_key=True)
    adjusted_price = models.FloatField(null=True, blank=True)
    average_price = models.FloatField(null=True, blank=True)
    updated_at = models.DateTimeField()

    class Meta:
        db_table = "esidata_market_price"


class SystemCostIndex(models.Model):
    system_id = models.IntegerField()
    activity = models.CharField(max_length=48)  # ESI activity name, e.g. "manufacturing"
    cost_index = models.FloatField()
    updated_at = models.DateTimeField()

    class Meta:
        db_table = "esidata_system_cost_index"
        constraints = [
            models.UniqueConstraint(
                fields=["system_id", "activity"], name="esidata_cost_index_uniq"
            )
        ]
