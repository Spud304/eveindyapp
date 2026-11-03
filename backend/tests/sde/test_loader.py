import pytest

from apps.core.importing import ImportFailed
from apps.sde.jsonl import DirSource, ZipSource, detect_build
from apps.sde.loader import import_source
from apps.sde.models import EveGroup, EveType, SdeBuild, SdeRawRecord

from .conftest import BUILD, make_sde_zip, tiny_records

pytestmark = pytest.mark.django_db


def run(path, **kwargs):
    with ZipSource(path) as source:
        detected, release_date = detect_build(source, path=path)
        build = kwargs.pop("build", detected)
        return import_source(source, build=build, release_date=release_date, **kwargs)


def test_full_import_lands_raw_and_typed_rows(tiny_zip):
    report = run(tiny_zip)
    assert report.ok
    assert report.files["types"].seen == 7 and report.files["types"].upserted == 7
    assert SdeRawRecord.objects.filter(file="types").count() == 7
    assert SdeRawRecord.objects.filter(file="_sde").count() == 0  # not in the include list
    assert report.derived == {
        "categories": 3,
        "groups": 4,
        "metaGroups": 2,
        "types": 6,
        "blueprints": 1,
        "blueprint_activities": 4,
        "mapSolarSystems": 1,
    }
    build = SdeBuild.latest()
    assert build is not None and build.build == BUILD and build.files
    assert build.release_date is not None and build.release_date.year == 2026
    assert build.counts["derived"]["types"] == 6


def test_nested_pairs_are_stored_decoded(tiny_zip):
    run(tiny_zip)
    source = SdeRawRecord.objects.get(file="industryModifierSources", key="35825").data
    assert source["manufacturing"]["material"][0]["dogmaAttributeID"] == 2600


def test_same_build_reimport_changes_nothing(tiny_zip):
    run(tiny_zip)
    before = list(EveType.objects.order_by("id").values())
    report = run(tiny_zip)
    assert report.files["types"].removed == 0
    assert list(EveType.objects.order_by("id").values()) == before
    assert SdeBuild.objects.count() == 1


def test_dropped_record_is_flagged_not_deleted_and_can_return(tiny_zip, tmp_path):
    run(tiny_zip)
    records = tiny_records()
    del records["types"][648]
    newer = tmp_path / f"eve-online-static-data-{BUILD + 1}-jsonl.zip"
    newer.write_bytes(make_sde_zip(records, build=BUILD + 1))
    report = run(newer, build=BUILD + 1)
    assert report.files["types"].removed == 1
    raw = SdeRawRecord.objects.get(file="types", key="648")
    assert raw.removed and raw.build == BUILD
    assert EveType.objects.get(pk=648).removed is True
    assert EveType.objects.get(pk=587).removed is False

    back = tmp_path / f"eve-online-static-data-{BUILD + 2}-jsonl.zip"
    back.write_bytes(make_sde_zip(tiny_records(), build=BUILD + 2))
    run(back, build=BUILD + 2)
    assert SdeRawRecord.objects.get(file="types", key="648").removed is False
    assert EveType.objects.get(pk=648).removed is False
    latest = SdeBuild.latest()
    assert latest is not None and latest.build == BUILD + 2


def test_older_build_refused_unless_forced(tiny_zip):
    run(tiny_zip)
    with pytest.raises(ImportFailed) as exc:
        run(tiny_zip, build=BUILD - 10)
    assert "--force" in exc.value.remediation
    report = run(tiny_zip, build=BUILD - 10, force=True)
    assert report.ok


def test_files_subset_and_raw_only(tiny_zip):
    report = run(tiny_zip, files=["races"], raw_only=True)
    assert list(report.files) == ["races"]
    assert SdeRawRecord.objects.filter(file="races").count() == 2
    assert EveType.objects.count() == 0 and SdeBuild.objects.count() == 0


def test_missing_included_file_is_a_warning(tiny_zip, settings):
    settings.SDE_INCLUDED_FILES = ["races", "nonexistent"]
    report = run(tiny_zip, raw_only=True)
    assert any("nonexistent" in w for w in report.warnings)
    assert report.ok


def test_dry_run_writes_nothing(tiny_zip):
    report = run(tiny_zip, dry_run=True)
    assert report.files["types"].seen == 7
    assert SdeRawRecord.objects.count() == 0 and EveType.objects.count() == 0


def test_dir_source_import(tiny_zip, tmp_path):
    import zipfile

    out = tmp_path / "extracted"
    with zipfile.ZipFile(tiny_zip) as zf:
        zf.extractall(out)
    with DirSource(out) as source:
        report = import_source(source, build=BUILD)
    assert report.ok and EveGroup.objects.get(pk=28).name == "Hauler"


def test_forced_older_build_becomes_the_live_build(tiny_zip, tmp_path):
    run(tiny_zip)
    records = tiny_records()
    del records["types"][648]  # only the newer build has it
    older = tmp_path / f"eve-online-static-data-{BUILD - 10}-jsonl.zip"
    older.write_bytes(make_sde_zip(records, build=BUILD - 10))
    run(older, build=BUILD - 10, force=True)
    assert SdeRawRecord.objects.get(file="types", key="648").removed
    assert EveType.objects.get(pk=648).removed is True
    latest = SdeBuild.latest()
    assert latest is not None and latest.build == BUILD - 10


def test_a_failed_file_leaves_the_previous_build_whole(tiny_zip, tmp_path, monkeypatch):
    from apps.sde import loader

    run(tiny_zip)
    newer = tmp_path / f"eve-online-static-data-{BUILD + 1}-jsonl.zip"
    newer.write_bytes(make_sde_zip(tiny_records(), build=BUILD + 1))
    real = loader.load_raw_file

    def load_then_break(source, name, build, report, **kwargs):
        real(source, name, build, report, **kwargs)
        if name == "types":
            raise RuntimeError("disk full")

    monkeypatch.setattr(loader, "load_raw_file", load_then_break)
    with pytest.raises(RuntimeError):
        run(newer, build=BUILD + 1)
    assert set(SdeRawRecord.objects.values_list("build", flat=True)) == {BUILD}
    latest = SdeBuild.latest()
    assert latest is not None and latest.build == BUILD


def test_check_latest_marks_the_check_only_when_up_to_date(tiny_zip, monkeypatch, settings):
    from django.core.management import CommandError, call_command

    from apps.sde import download

    run(tiny_zip)
    settings.SDE_AUTO_DOWNLOAD = True

    def broken(build, dest, client=None):
        raise ImportFailed("download failed", "retry later")

    monkeypatch.setattr(
        download, "fetch_latest_build", lambda: download.LatestBuild(BUILD + 1, None)
    )
    monkeypatch.setattr(download, "download_build", broken)
    with pytest.raises(CommandError):
        call_command("import_sde", "--check-latest")
    latest = SdeBuild.latest()
    assert latest is not None and latest.last_checked_at is None  # health keeps saying stale

    monkeypatch.setattr(download, "fetch_latest_build", lambda: download.LatestBuild(BUILD, None))
    call_command("import_sde", "--check-latest")
    latest = SdeBuild.latest()
    assert latest is not None and latest.last_checked_at is not None
