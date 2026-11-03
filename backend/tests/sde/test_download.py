import json
from collections import namedtuple

import httpx
import pytest

from apps.core.importing import ImportFailed
from apps.sde import download

from .conftest import BUILD, RELEASE, make_sde_zip, tiny_records

LATEST = "https://developers.eveonline.com/static-data/tranquility/latest.jsonl"
LATEST_ZIP = "https://developers.eveonline.com/static-data/eve-online-static-data-latest-jsonl.zip"


def build_url(build):
    return f"https://developers.eveonline.com/static-data/tranquility/eve-online-static-data-{build}-jsonl.zip"


def make_client(zip_bytes, *, build=BUILD, content_length=None, fail_first=0):
    calls = {"zip": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == LATEST:
            return httpx.Response(
                200, text=json.dumps({"_key": "sde", "buildNumber": build, "releaseDate": RELEASE})
            )
        if url == LATEST_ZIP:
            return httpx.Response(302, headers={"Location": build_url(build)})
        if url == build_url(build):
            calls["zip"] += 1
            if calls["zip"] <= fail_first:
                return httpx.Response(503)
            headers = {
                "Content-Length": str(
                    content_length if content_length is not None else len(zip_bytes)
                )
            }
            return httpx.Response(200, content=zip_bytes, headers=headers)
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    return client, calls


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(download.time, "sleep", lambda s: None)


def test_fetch_latest_build():
    client, _ = make_client(b"")
    latest = download.fetch_latest_build(client)
    assert latest.build == BUILD
    assert latest.release_date is not None and latest.release_date.year == 2026


def test_download_follows_redirect_and_verifies_build(tmp_path):
    zip_bytes = make_sde_zip(tiny_records())
    client, calls = make_client(zip_bytes)
    path = download.download_build(BUILD, tmp_path, client)
    assert path.name == f"eve-online-static-data-{BUILD}-jsonl.zip"
    assert path.read_bytes() == zip_bytes and calls["zip"] == 1
    assert not list(tmp_path.glob(".partial-*"))
    # second call is a no-op
    download.download_build(BUILD, tmp_path, client)
    assert calls["zip"] == 1


def test_retries_then_succeeds_on_5xx(tmp_path):
    zip_bytes = make_sde_zip(tiny_records())
    client, calls = make_client(zip_bytes, fail_first=2)
    download.download_build(BUILD, tmp_path, client)
    assert calls["zip"] == 3


def test_short_read_fails_after_retries(tmp_path):
    zip_bytes = make_sde_zip(tiny_records())
    client, calls = make_client(zip_bytes, content_length=len(zip_bytes) + 100)
    with pytest.raises(ImportFailed) as exc:
        download.download_build(BUILD, tmp_path, client)
    assert "3 attempts" in str(exc.value) and calls["zip"] == 3
    assert not list(tmp_path.glob("*.zip"))


def test_wrong_build_in_archive_rejected(tmp_path):
    zip_bytes = make_sde_zip(tiny_records(), build=BUILD + 5)
    client, _ = make_client(zip_bytes)
    with pytest.raises(ImportFailed) as exc:
        download.download_build(BUILD, tmp_path, client)
    assert "expected" in str(exc.value)


def test_disk_space_checked_before_streaming(tmp_path, monkeypatch):
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(download.shutil, "disk_usage", lambda p: Usage(1, 1, 10))
    client, _ = make_client(make_sde_zip(tiny_records()))
    with pytest.raises(ImportFailed) as exc:
        download.download_build(BUILD, tmp_path, client)
    assert "free" in str(exc.value)


def test_prune_keeps_newest_two(tmp_path):
    for b in (1, 2, 3, 4):
        (tmp_path / f"eve-online-static-data-{b}-jsonl.zip").write_bytes(b"x")
    (tmp_path / "unrelated.zip").write_bytes(b"x")
    removed = download.prune_downloads(tmp_path, keep=2)
    assert sorted(p.name for p in removed) == [
        "eve-online-static-data-1-jsonl.zip",
        "eve-online-static-data-2-jsonl.zip",
    ]
    assert (tmp_path / "unrelated.zip").exists()


def test_a_stale_zip_on_disk_is_downloaded_again(tmp_path):
    stale = download.download_path(tmp_path, BUILD)
    stale.write_bytes(make_sde_zip(tiny_records(), build=BUILD - 1))
    client, calls = make_client(make_sde_zip(tiny_records()))
    download.download_build(BUILD, tmp_path, client)
    assert calls["zip"] == 1


def test_an_archive_without_a_build_record_is_refused(tmp_path):
    client, _ = make_client(make_sde_zip(tiny_records(), build=None))
    with pytest.raises(ImportFailed) as exc:
        download.download_build(BUILD, tmp_path, client)
    assert "_sde.jsonl" in str(exc.value)


def test_a_garbled_build_pointer_is_an_import_error():
    def handler(request):
        return httpx.Response(200, text="<html>maintenance</html>")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(ImportFailed):
        download.fetch_latest_build(client)
