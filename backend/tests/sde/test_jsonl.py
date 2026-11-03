import io
import json
import zipfile

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from apps.core.importing import ImportFailed
from apps.sde.jsonl import (
    DirSource,
    ZipSource,
    decode_pairs,
    detect_build,
    iter_records,
    open_source,
)

from .conftest import BUILD, encode_pairs, make_sde_zip, tiny_records


class TestDecodePairs:
    def test_pair_list_with_values_becomes_dict(self):
        assert decode_pairs([{"_key": 1, "_value": "a"}, {"_key": 2, "_value": [1, 2]}]) == {
            1: "a",
            2: [1, 2],
        }

    def test_pair_list_with_inline_fields(self):
        raw = [{"_key": 3329, "bonus": 7.5, "unitID": 105}]
        assert decode_pairs(raw) == {3329: {"bonus": 7.5, "unitID": 105}}

    def test_nested_pairs_recurse(self):
        raw = {
            "masteries": [
                {"_key": 0, "_value": [96, 99]},
                {"_key": 1, "_value": [{"_key": 7, "_value": "x"}]},
            ]
        }
        assert decode_pairs(raw) == {"masteries": {0: [96, 99], 1: {7: "x"}}}

    def test_plain_lists_and_scalars_untouched(self):
        raw = {"dogmaAttributes": [{"attributeID": 3, "value": 0.0}], "n": 5, "s": "x", "empty": []}
        assert decode_pairs(raw) == raw

    def test_mixed_list_left_alone_with_warning(self):
        warnings: list[str] = []
        raw = [{"_key": 1, "_value": 2}, {"other": 3}]
        assert decode_pairs(raw, warnings, "f") == raw
        assert warnings and "mixes" in warnings[0]

    def test_extra_fields_beside_value_warn(self):
        warnings: list[str] = []
        decode_pairs([{"_key": 1, "_value": 2, "junk": 3}], warnings, "f")
        assert warnings and "extra fields" in warnings[0]


json_scalars = (
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(max_size=8)
)
safe_keys = st.text(min_size=1, max_size=6).filter(lambda k: k not in ("_key", "_value"))


def _nested(children):
    return (
        st.lists(children, max_size=3)
        | st.dictionaries(safe_keys, children, max_size=3)
        | st.dictionaries(
            st.integers(min_value=0, max_value=5000), children, min_size=1, max_size=3
        )
    )


@settings(max_examples=150, deadline=None)
@given(st.recursive(json_scalars, _nested, max_leaves=12))
def test_decode_inverts_encode(value):
    assert decode_pairs(encode_pairs(value)) == value


class TestIterRecords:
    def test_yields_key_and_stripped_record(self):
        text = io.StringIO(
            '{"_key": 587, "name": {"en": "Rifter"}}\n\n{"_key": "sde", "buildNumber": 1}\n'
        )
        rows = list(iter_records(text, file="types"))
        assert rows == [("587", {"name": {"en": "Rifter"}}), ("sde", {"buildNumber": 1})]

    def test_missing_key_is_a_clear_failure(self):
        with pytest.raises(ImportFailed) as exc:
            list(iter_records(io.StringIO('{"typeID": 587}\n'), file="types"))
        assert "no _key" in str(exc.value) and "September 2025" in exc.value.remediation

    def test_bad_json_names_the_line(self):
        with pytest.raises(ImportFailed) as exc:
            list(iter_records(io.StringIO('{"_key": 1}\n{oops\n'), file="types"))
        assert "line 2" in str(exc.value)


class TestSources:
    def test_zip_source_lists_root_members(self, tiny_zip):
        with ZipSource(tiny_zip) as source:
            assert "types" in source.names() and "_sde" in source.names()
            with source.open("races") as text:
                assert len([line for line in text if line.strip()]) == 2

    def test_dir_source(self, tmp_path):
        (tmp_path / "races.jsonl").write_text(
            json.dumps({"_key": 2, "name": {"en": "Minmatar"}}) + "\n"
        )
        source = DirSource(tmp_path)
        assert source.names() == ["races"]
        assert open_source(tmp_path).names() == ["races"]

    def test_empty_dir_is_a_failure(self, tmp_path):
        with pytest.raises(ImportFailed):
            DirSource(tmp_path)

    def test_not_a_zip(self, tmp_path):
        bad = tmp_path / "x.zip"
        bad.write_bytes(b"nope")
        with pytest.raises(ImportFailed):
            ZipSource(bad)

    def test_duplicate_member_rejected(self, tmp_path):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("types.jsonl", "")
            zf.writestr("sub/types.jsonl", "")
        path = tmp_path / "dup.zip"
        path.write_bytes(buf.getvalue())
        with pytest.raises(ImportFailed):
            ZipSource(path)


class TestDetectBuild:
    def test_from_sde_member(self, tiny_zip):
        with ZipSource(tiny_zip) as source:
            build, release = detect_build(source, path=tiny_zip)
        assert build == BUILD and release is not None and release.year == 2026

    def test_from_filename_when_member_missing(self, tmp_path):
        path = tmp_path / "eve-online-static-data-42-jsonl.zip"
        path.write_bytes(make_sde_zip({"races": tiny_records()["races"]}, build=None))
        with ZipSource(path) as source:
            assert detect_build(source, path=path) == (42, None)

    def test_override_wins(self, tiny_zip):
        with ZipSource(tiny_zip) as source:
            assert detect_build(source, path=tiny_zip, override=7)[0] == 7

    def test_undetectable_fails_with_remediation(self, tmp_path):
        path = tmp_path / "mystery.zip"
        path.write_bytes(make_sde_zip({"races": tiny_records()["races"]}, build=None))
        with ZipSource(path) as source, pytest.raises(ImportFailed) as exc:
            detect_build(source, path=path)
        assert "--build" in exc.value.remediation
