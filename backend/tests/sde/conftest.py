"""Builds tiny CCP-shaped SDE archives in memory."""

import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

BUILD = 3503375
RELEASE = "2026-09-10T11:09:04Z"


def encode_pairs(value: Any) -> Any:
    """Inverse of jsonl.decode_pairs: int-keyed dicts become CCP's `_key`/`_value` lists."""
    if isinstance(value, dict):
        if value and all(isinstance(k, int) for k in value):
            out = []
            for k, v in value.items():
                encoded = encode_pairs(v)
                # CCP inlines object values; anything else (including an int-keyed map,
                # which encodes to a list) goes under _value.
                if isinstance(encoded, dict):
                    out.append({"_key": k, **encoded})
                else:
                    out.append({"_key": k, "_value": encoded})
            return out
        return {k: encode_pairs(v) for k, v in value.items()}
    if isinstance(value, list):
        return [encode_pairs(v) for v in value]
    return value


def names(en: str) -> dict:
    return {"de": en, "en": en, "fr": en, "ja": en, "ko": en, "ru": en, "zh": en, "es": en}


def tiny_records() -> dict[str, dict[int, dict]]:
    """Real ids: Rifter 587 (Frigate 25, Ship 6), Rifter Blueprint 691, Tritanium 34, Jita."""
    return {
        "categories": {
            4: {"name": names("Material"), "published": True},
            6: {"name": names("Ship"), "published": True},
            9: {"name": names("Blueprint"), "published": True},
        },
        "groups": {
            18: {"categoryID": 4, "name": names("Mineral"), "published": True},
            25: {"categoryID": 6, "name": names("Frigate"), "published": True},
            28: {"categoryID": 6, "name": names("Hauler"), "published": True},
            105: {"categoryID": 9, "name": names("Frigate Blueprint"), "published": True},
        },
        "metaGroups": {
            1: {"name": names("Tech I")},
            2: {"name": names("Tech II"), "iconID": 24150, "iconSuffix": "t2"},
        },
        "races": {1: {"name": names("Caldari")}, 2: {"name": names("Minmatar")}},
        "types": {
            587: {
                "groupID": 25,
                "name": names("Rifter"),
                "published": True,
                "portionSize": 1,
                "metaGroupID": 1,
                "techLevel": 1,
                "metaLevel": 0,
                "volume": 27289.0,
                "packagedVolume": 2500.0,
                "basePrice": 400000.0,
                "marketGroupID": 64,
            },
            648: {"groupID": 28, "name": names("Badger"), "published": True, "portionSize": 1},
            600: {
                "groupID": 25,
                "name": names("Odd Frigate"),
                "published": True,
                "metaGroupID": 999,
            },
            999999: {"groupID": 25, "name": names("Unpublished Thing"), "published": False},
            34: {"groupID": 18, "name": names("Tritanium"), "published": True, "portionSize": 1},
            691: {"groupID": 105, "name": names("Rifter Blueprint"), "published": True},
            5000: {"groupID": 77777, "name": names("Orphan"), "published": True},
        },
        "blueprints": {
            691: {
                "blueprintTypeID": 691,
                "maxProductionLimit": 30,
                "activities": {
                    "copying": {"time": 4800},
                    "manufacturing": {
                        "materials": [{"quantity": 32000, "typeID": 34}],
                        "products": [{"quantity": 1, "typeID": 587}],
                        "skills": [{"level": 1, "typeID": 3380}],
                        "time": 6000,
                    },
                    "invention": {
                        "materials": [{"quantity": 2, "typeID": 20416}],
                        "products": [{"probability": 0.3, "quantity": 1, "typeID": 11371}],
                        "time": 63900,
                    },
                    "research_material": {"time": 2100},
                },
            }
        },
        "mapSolarSystems": {
            30000142: {
                "name": names("Jita"),
                "securityStatus": 0.945913,
                "regionID": 10000002,
                "constellationID": 20000020,
            }
        },
        "typeDogma": {
            35825: {"dogmaAttributes": [{"attributeID": 2600, "value": 0.99}]},
        },
        "industryModifierSources": {
            35825: {"manufacturing": {"material": [{"dogmaAttributeID": 2600}]}},
        },
    }


def make_sde_zip(
    records: dict[str, dict[int, dict]], build: int | None = BUILD, release: str | None = RELEASE
) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for file, rows in records.items():
            lines = [
                json.dumps({"_key": k, **encode_pairs(v)}, ensure_ascii=False)
                for k, v in rows.items()
            ]
            zf.writestr(f"{file}.jsonl", "\n".join(lines) + "\n")
        if build is not None:
            info = {"_key": "sde", "buildNumber": build}
            if release:
                info["releaseDate"] = release
            zf.writestr("_sde.jsonl", json.dumps(info) + "\n")
    return buf.getvalue()


@pytest.fixture
def tiny_zip(tmp_path, sde_dir) -> Path:
    path = tmp_path / f"eve-online-static-data-{BUILD}-jsonl.zip"
    path.write_bytes(make_sde_zip(tiny_records()))
    return path
