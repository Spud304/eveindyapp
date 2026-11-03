"""SDE mirror. Written only by the importer; typed rows are flagged removed, never deleted.

Blueprint activity rows (materials, products, skills) are children of a blueprint and are
rebuilt on every import, so they always match the live build.
"""

from typing import TYPE_CHECKING

from django.db import models


class SdeRawRecord(models.Model):
    """One decoded SDE record from any included file."""

    file = models.CharField(max_length=64)
    key = models.CharField(max_length=64)
    data = models.JSONField()
    build = models.PositiveIntegerField()
    removed = models.BooleanField(default=False)

    class Meta:
        db_table = "sde_raw_record"
        constraints = [
            models.UniqueConstraint(fields=["file", "key"], name="sde_raw_record_file_key_uniq")
        ]
        indexes = [models.Index(fields=["file", "build"], name="sde_raw_record_file_build_idx")]

    def __str__(self) -> str:
        return f"{self.file}:{self.key}"


class SdeBuild(models.Model):
    """One row per imported SDE build; the most recently imported is the live build."""

    build = models.PositiveIntegerField(unique=True)
    release_date = models.DateTimeField(null=True, blank=True)
    imported_at = models.DateTimeField()
    last_checked_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=300, blank=True)
    files = models.JSONField(default=list, blank=True)
    counts = models.JSONField(default=dict, blank=True)
    duration_s = models.FloatField(default=0.0)

    class Meta:
        db_table = "sde_build"
        ordering = ["-build"]

    def __str__(self) -> str:
        return f"SDE build {self.build}"

    @classmethod
    def latest(cls) -> "SdeBuild | None":
        # By import time, not build number: after a forced import of an older build, that build
        # is what the tables hold.
        return cls.objects.order_by("-imported_at", "-build").first()


class EveCategory(models.Model):
    id = models.IntegerField(primary_key=True)
    name = models.CharField(max_length=100)
    published = models.BooleanField(default=False)
    removed = models.BooleanField(default=False)

    class Meta:
        db_table = "sde_eve_category"
        verbose_name_plural = "eve categories"

    def __str__(self) -> str:
        return self.name


class EveGroup(models.Model):
    id = models.IntegerField(primary_key=True)
    category = models.ForeignKey(EveCategory, on_delete=models.PROTECT, related_name="groups")
    name = models.CharField(max_length=100)
    published = models.BooleanField(default=False)
    removed = models.BooleanField(default=False)

    if TYPE_CHECKING:
        category_id: int

    class Meta:
        db_table = "sde_eve_group"

    def __str__(self) -> str:
        return self.name


class EveMetaGroup(models.Model):
    id = models.IntegerField(primary_key=True)
    name = models.CharField(max_length=100)

    class Meta:
        db_table = "sde_eve_meta_group"

    def __str__(self) -> str:
        return self.name


class EveType(models.Model):
    """Every SDE type: items, blueprints, skills, structures, rigs."""

    id = models.IntegerField(primary_key=True)
    group = models.ForeignKey(EveGroup, on_delete=models.PROTECT, related_name="types")
    name = models.CharField(max_length=200)
    published = models.BooleanField(default=False)
    removed = models.BooleanField(default=False)
    meta_group = models.ForeignKey(
        EveMetaGroup, null=True, blank=True, on_delete=models.PROTECT, related_name="types"
    )
    tech_level = models.SmallIntegerField(null=True, blank=True)
    meta_level = models.SmallIntegerField(null=True, blank=True)
    volume = models.FloatField(null=True, blank=True)
    packaged_volume = models.FloatField(null=True, blank=True)
    portion_size = models.IntegerField(null=True, blank=True)
    base_price = models.FloatField(null=True, blank=True)
    market_group_id = models.IntegerField(null=True, blank=True)

    if TYPE_CHECKING:
        group_id: int
        meta_group_id: int | None

    class Meta:
        db_table = "sde_eve_type"
        indexes = [models.Index(fields=["name"], name="sde_eve_type_name_idx")]

    def __str__(self) -> str:
        return self.name


class Blueprint(models.Model):
    """A blueprint or reaction formula. `id` is its type id."""

    id = models.IntegerField(primary_key=True)
    max_production_limit = models.IntegerField()
    removed = models.BooleanField(default=False)

    class Meta:
        db_table = "sde_blueprint"

    def __str__(self) -> str:
        return f"blueprint {self.id}"


class BlueprintActivity(models.Model):
    blueprint = models.ForeignKey(Blueprint, on_delete=models.CASCADE, related_name="activities")
    activity = models.CharField(max_length=32)
    time = models.IntegerField()

    if TYPE_CHECKING:
        blueprint_id: int

    class Meta:
        db_table = "sde_blueprint_activity"
        constraints = [
            models.UniqueConstraint(
                fields=["blueprint", "activity"], name="sde_blueprint_activity_uniq"
            )
        ]


class BlueprintMaterial(models.Model):
    activity = models.ForeignKey(
        BlueprintActivity, on_delete=models.CASCADE, related_name="materials"
    )
    type_id = models.IntegerField()
    quantity = models.IntegerField()

    class Meta:
        db_table = "sde_blueprint_material"


class BlueprintProduct(models.Model):
    activity = models.ForeignKey(
        BlueprintActivity, on_delete=models.CASCADE, related_name="products"
    )
    type_id = models.IntegerField(db_index=True)
    quantity = models.IntegerField()
    probability = models.FloatField(null=True, blank=True)  # invention only

    class Meta:
        db_table = "sde_blueprint_product"


class BlueprintSkill(models.Model):
    activity = models.ForeignKey(BlueprintActivity, on_delete=models.CASCADE, related_name="skills")
    skill_id = models.IntegerField()
    level = models.SmallIntegerField()

    class Meta:
        db_table = "sde_blueprint_skill"


class SolarSystem(models.Model):
    id = models.IntegerField(primary_key=True)
    name = models.CharField(max_length=100)
    security = models.FloatField()  # raw securityStatus
    region_id = models.IntegerField(null=True, blank=True)
    constellation_id = models.IntegerField(null=True, blank=True)
    removed = models.BooleanField(default=False)

    class Meta:
        db_table = "sde_solar_system"
        indexes = [models.Index(fields=["name"], name="sde_solar_system_name_idx")]

    def __str__(self) -> str:
        return self.name
