"""Copy the SDE records the golden tests need out of CCP's JSONL zip, unchanged.

    uv run python -m tests.golden.extract <eve-online-static-data-<build>-jsonl.zip>

Writes `tests/golden/sde/<file>.jsonl`: the chosen blueprints, every type they make or use,
the structures, rigs, skills and decryptors, their groups and categories, and two systems.
Lines are copied as CCP wrote them, so the tests read the real format through the real
importer. Run it again after a new SDE build and diff the fixture to see what changed."""

import json
import sys
import zipfile
from pathlib import Path

OUT = Path(__file__).parent / "sde"

BLUEPRINTS = {
    691,  # Rifter Blueprint
    46207,  # Tungsten Carbide Reaction Formula
    45732,  # Test Reaction Blueprint (unpublished; also makes Tungsten Carbide)
    23528,  # Drone Link Augmentor I Blueprint (copied and invented from)
    24428,  # Drone Link Augmentor II Blueprint
}
STRUCTURES_AND_RIGS = {
    35826,  # Azbel
    35836,  # Tatara
    37146,  # Standup M-Set Basic Medium Ship Manufacturing Material Efficiency I
    37154,  # Standup M-Set Basic Small Ship Manufacturing Material Efficiency I
    46486,  # Standup M-Set Composite Reactor Material Efficiency I
    43880,  # Standup M-Set Invention Accelerator I
    45544,  # Standup M-Set Thukker Basic Capital Component Manufacturing Material Efficiency
    45640,  # Standup M-Set Thukker Advanced Component Manufacturing Material Efficiency
    47883,  # Upwell A1F Outpost Rig
}
SKILLS = {3380, 3388, 3402, 45746}  # Industry, Advanced Industry, Science, Reactions
DECRYPTOR_GROUP = 1304
SYSTEMS = {30000142, 30001761}  # Jita (high), D-JVGJ (null)


def read(zf: zipfile.ZipFile, name: str) -> list[str]:
    with zf.open(f"{name}.jsonl") as fh:
        return fh.read().decode().splitlines()


def keyed(lines: list[str]) -> dict[int, tuple[str, dict]]:
    out = {}
    for line in lines:
        rec = json.loads(line)
        out[rec["_key"]] = (line, rec)
    return out


def main(path: str) -> None:
    with zipfile.ZipFile(path) as zf:
        files = {n.removesuffix(".jsonl") for n in zf.namelist()}
        blueprints = keyed(read(zf, "blueprints"))
        types = keyed(read(zf, "types"))
        types_wanted = set(BLUEPRINTS) | STRUCTURES_AND_RIGS | SKILLS
        for bp_id in BLUEPRINTS:
            for activity in blueprints[bp_id][1].get("activities", {}).values():
                for key in ("materials", "products"):
                    types_wanted |= {m["typeID"] for m in activity.get(key, [])}
                types_wanted |= {s["typeID"] for s in activity.get("skills", [])}
        types_wanted |= {k for k, (_, t) in types.items() if t.get("groupID") == DECRYPTOR_GROUP}
        groups_wanted = {types[t][1]["groupID"] for t in types_wanted}
        groups = keyed(read(zf, "groups"))
        categories_wanted = {groups[g][1]["categoryID"] for g in groups_wanted}
        filters_wanted = set()
        sources = keyed(read(zf, "industryModifierSources"))
        for t in STRUCTURES_AND_RIGS:
            for kinds in sources.get(t, ("", {}))[1].values():
                if isinstance(kinds, dict):
                    for entries in kinds.values():
                        filters_wanted |= {e["filterID"] for e in entries if "filterID" in e}

        dogma = keyed(read(zf, "typeDogma"))
        effects_wanted = {
            e["effectID"]
            for t in STRUCTURES_AND_RIGS
            for e in dogma.get(t, ("", {}))[1].get("dogmaEffects", [])
        }
        wanted = {
            "blueprints": BLUEPRINTS,
            "dogmaEffects": effects_wanted,
            "types": types_wanted,
            "groups": groups_wanted,
            "categories": categories_wanted,
            "metaGroups": None,  # all (a handful)
            "typeDogma": types_wanted,
            "industryModifierSources": STRUCTURES_AND_RIGS,
            "industryTargetFilters": filters_wanted,
            "mapSolarSystems": SYSTEMS,
        }
        OUT.mkdir(exist_ok=True)
        for name, keys in wanted.items():
            assert name in files, f"{name}.jsonl missing from {path}"
            lines = [
                line for line in read(zf, name) if keys is None or json.loads(line)["_key"] in keys
            ]
            (OUT / f"{name}.jsonl").write_text("\n".join(lines) + "\n")
            print(f"{name}: {len(lines)}")
        (OUT / "_sde.jsonl").write_text("\n".join(read(zf, "_sde")) + "\n")


if __name__ == "__main__":
    main(sys.argv[1])
