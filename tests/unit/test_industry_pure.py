"""Tests for pure functions in src/industry.py — no DB or mocking needed."""

import math
from unittest.mock import MagicMock

from src.industry import (
    _get_security_class,
    _classify_product_for_rig,
    _compute_station_me,
    _pick_best_station,
    _discover_blueprints,
    _resolve_material_tree,
    _compute_runs_needed,
    _describe_ownership,
)
from src.industry_constants import (
    BASIC_SMALL_SHIP_GROUPS,
    BASIC_MEDIUM_SHIP_GROUPS,
    BASIC_LARGE_SHIP_GROUPS,
    ADV_SMALL_SHIP_GROUPS,
    ADV_MEDIUM_SHIP_GROUPS,
    ADV_LARGE_SHIP_GROUPS,
    CAPITAL_SHIP_GROUPS,
)


# --- _get_security_class ---


class TestGetSecurityClass:
    def test_highsec_above_threshold(self):
        assert _get_security_class(1.0) == "hs"
        assert _get_security_class(0.5) == "hs"

    def test_highsec_at_threshold(self):
        assert _get_security_class(0.45) == "hs"

    def test_lowsec(self):
        assert _get_security_class(0.44) == "ls"
        assert _get_security_class(0.1) == "ls"

    def test_nullsec(self):
        assert _get_security_class(0.0) == "ns"
        assert _get_security_class(-0.5) == "ns"

    def test_none_defaults_highsec(self):
        assert _get_security_class(None) == "hs"


# --- _classify_product_for_rig ---


class TestClassifyProductForRig:
    def test_equipment(self):
        assert _classify_product_for_rig(1, {1: 50}, {50: 7}) == "equipment"

    def test_ammunition(self):
        assert _classify_product_for_rig(1, {1: 50}, {50: 8}) == "ammunition"

    def test_drone_fighter_cat18(self):
        assert _classify_product_for_rig(1, {1: 50}, {50: 18}) == "drone_fighter"

    def test_drone_fighter_cat87(self):
        assert _classify_product_for_rig(1, {1: 50}, {50: 87}) == "drone_fighter"

    def test_basic_small_ship(self):
        gid = next(iter(BASIC_SMALL_SHIP_GROUPS))
        assert _classify_product_for_rig(1, {1: gid}, {gid: 6}) == "basic_small_ship"

    def test_basic_medium_ship(self):
        gid = next(iter(BASIC_MEDIUM_SHIP_GROUPS))
        assert _classify_product_for_rig(1, {1: gid}, {gid: 6}) == "basic_medium_ship"

    def test_basic_large_ship(self):
        gid = next(iter(BASIC_LARGE_SHIP_GROUPS))
        assert _classify_product_for_rig(1, {1: gid}, {gid: 6}) == "basic_large_ship"

    def test_adv_small_ship(self):
        gid = next(iter(ADV_SMALL_SHIP_GROUPS))
        assert _classify_product_for_rig(1, {1: gid}, {gid: 6}) == "adv_small_ship"

    def test_adv_medium_ship(self):
        gid = next(iter(ADV_MEDIUM_SHIP_GROUPS))
        assert _classify_product_for_rig(1, {1: gid}, {gid: 6}) == "adv_medium_ship"

    def test_adv_large_ship(self):
        gid = next(iter(ADV_LARGE_SHIP_GROUPS))
        assert _classify_product_for_rig(1, {1: gid}, {gid: 6}) == "adv_large_ship"

    def test_capital_ship(self):
        gid = next(iter(CAPITAL_SHIP_GROUPS))
        assert _classify_product_for_rig(1, {1: gid}, {gid: 6}) == "capital_ship"

    def test_adv_component(self):
        assert _classify_product_for_rig(1, {1: 334}, {334: 17}) == "adv_component"
        assert _classify_product_for_rig(1, {1: 964}, {964: 17}) == "adv_component"

    def test_basic_capital_component(self):
        assert (
            _classify_product_for_rig(1, {1: 873}, {873: 17})
            == "basic_capital_component"
        )
        assert (
            _classify_product_for_rig(1, {1: 913}, {913: 17})
            == "basic_capital_component"
        )

    def test_structure_cat17(self):
        assert _classify_product_for_rig(1, {1: 536}, {536: 17}) == "structure"

    def test_structure_cat65(self):
        assert _classify_product_for_rig(1, {1: 50}, {50: 65}) == "structure"

    def test_unknown_type(self):
        assert _classify_product_for_rig(999, {}, {}) is None

    def test_unknown_category(self):
        assert _classify_product_for_rig(1, {1: 50}, {50: 999}) is None

    def test_unknown_ship_group_in_cat6(self):
        assert _classify_product_for_rig(1, {1: 99999}, {99999: 6}) is None

    def test_unknown_group_in_cat17(self):
        assert _classify_product_for_rig(1, {1: 999}, {999: 17}) is None


# --- _compute_station_me ---


class TestComputeStationMe:
    def test_raitaru_no_rigs(self):
        station = {"structure_type": "raitaru", "rigs": [None, None, None]}
        result = _compute_station_me(station, "equipment", 0.9, {})
        assert abs(result - 1.0) < 0.001

    def test_unknown_structure_no_rigs(self):
        station = {"structure_type": "unknown", "rigs": []}
        result = _compute_station_me(station, "equipment", 0.9, {})
        assert result == 0.0

    def test_with_matching_rig(self):
        rig_data = {
            12345: {
                "me_bonus": 2.0,
                "sec_mult": {"hs": 1.0, "ls": 1.9, "ns": 2.1},
                "group_id": 1816,  # equipment M-Set
            }
        }
        station = {"structure_type": "raitaru", "rigs": [12345, None, None]}
        result = _compute_station_me(station, "equipment", 0.9, rig_data)
        expected = (1 - (1 - 0.01) * (1 - 0.02)) * 100
        assert abs(result - expected) < 0.001

    def test_with_non_matching_rig(self):
        rig_data = {
            12345: {
                "me_bonus": 2.0,
                "sec_mult": {"hs": 1.0, "ls": 1.9, "ns": 2.1},
                "group_id": 1816,  # equipment M-Set
            }
        }
        station = {"structure_type": "raitaru", "rigs": [12345, None, None]}
        result = _compute_station_me(station, "ammunition", 0.9, rig_data)
        assert abs(result - 1.0) < 0.001

    def test_lowsec_security_multiplier(self):
        rig_data = {
            12345: {
                "me_bonus": 2.0,
                "sec_mult": {"hs": 1.0, "ls": 1.9, "ns": 2.1},
                "group_id": 1816,
            }
        }
        station = {"structure_type": "raitaru", "rigs": [12345, None, None]}
        result = _compute_station_me(station, "equipment", 0.3, rig_data)
        rig_effective = 2.0 * 1.9 / 100
        expected = (1 - (1 - 0.01) * (1 - rig_effective)) * 100
        assert abs(result - expected) < 0.001

    def test_sotiyo_base_me(self):
        station = {"structure_type": "sotiyo", "rigs": []}
        result = _compute_station_me(station, "equipment", 0.9, {})
        assert abs(result - 1.0) < 0.001

    def test_athanor_no_base_me(self):
        station = {"structure_type": "athanor", "rigs": []}
        result = _compute_station_me(station, "equipment", 0.9, {})
        assert result == 0.0


# --- _pick_best_station ---


class TestPickBestStation:
    def test_empty_list(self):
        station, me = _pick_best_station([], "equipment", {}, {})
        assert station is None
        assert me == 0.0

    def test_picks_higher_me(self):
        rig_data = {
            100: {
                "me_bonus": 2.0,
                "sec_mult": {"hs": 1.0, "ls": 1.9, "ns": 2.1},
                "group_id": 1816,
            }
        }
        stations = [
            {
                "id": 1,
                "structure_type": "raitaru",
                "rigs": [None, None, None],
                "system_id": 1,
            },
            {
                "id": 2,
                "structure_type": "raitaru",
                "rigs": [100, None, None],
                "system_id": 2,
            },
        ]
        sec = {1: 0.9, 2: 0.9}
        best, me = _pick_best_station(stations, "equipment", sec, rig_data)
        assert best["id"] == 2
        assert me > 1.0


# --- _discover_blueprints ---


class TestDiscoverBlueprints:
    def test_single_blueprint(self):
        mats = {100: [(34, 2000), (35, 1000)]}
        result = _discover_blueprints(100, set(), mats, {})
        assert result == {100}

    def test_nested_chain(self):
        mats = {100: [(200, 10), (34, 500)], 201: [(34, 100)]}
        prods = {200: (201, 1)}
        result = _discover_blueprints(100, set(), mats, prods)
        assert result == {100, 201}

    def test_blacklist_skips_subtree(self):
        mats = {100: [(200, 10), (34, 500)], 201: [(34, 100)]}
        prods = {200: (201, 1)}
        result = _discover_blueprints(100, set(), mats, prods, blacklist={200})
        assert result == {100}

    def test_cycle_detection(self):
        mats = {100: [(200, 1)], 201: [(300, 1)], 301: [(200, 1)]}
        prods = {200: (201, 1), 300: (301, 1)}
        result = _discover_blueprints(100, set(), mats, prods)
        assert 100 in result

    def test_already_discovered(self):
        mats = {100: [(34, 100)]}
        result = _discover_blueprints(100, {100}, mats, {})
        assert result == {100}


# --- _resolve_material_tree ---


class TestResolveMaterialTree:
    def test_flat_tree_me0(self):
        mats = {100: [(34, 2000), (35, 1000)]}
        result = _resolve_material_tree(100, {}, {100: 0}, mats, {})
        assert result == {34: 2000, 35: 1000}

    def test_flat_tree_me10(self):
        mats = {100: [(34, 2000), (35, 1000)]}
        result = _resolve_material_tree(100, {}, {100: 10}, mats, {})
        assert result == {34: math.ceil(2000 * 0.9), 35: math.ceil(1000 * 0.9)}

    def test_nested_tree(self):
        mats = {100: [(200, 10)], 201: [(34, 100)]}
        prods = {200: (201, 1)}
        result = _resolve_material_tree(100, {}, {100: 0, 201: 0}, mats, prods)
        # 10 runs of bp 201, each needs 100 tritanium = 1000
        assert result == {34: 1000}

    def test_structure_me(self):
        mats = {100: [(34, 2000)]}
        struct_me = {100: 4.0}
        result = _resolve_material_tree(
            100, {}, {100: 10}, mats, {}, structure_me_by_bp=struct_me
        )
        expected = math.ceil(2000 * 0.9 * 0.96)
        assert result == {34: expected}

    def test_blacklist_stops_recursion(self):
        mats = {100: [(200, 10), (34, 500)], 201: [(34, 100)]}
        prods = {200: (201, 1)}
        result = _resolve_material_tree(100, {}, {100: 0}, mats, prods, blacklist={200})
        # 200 treated as raw material, not recursed
        assert result == {200: 10, 34: 500}

    def test_min_quantity_one(self):
        mats = {100: [(34, 1)]}
        result = _resolve_material_tree(100, {}, {100: 10}, mats, {})
        # max(1, ceil(1 * 0.9)) = 1
        assert result == {34: 1}


# --- _compute_runs_needed ---


class TestComputeRunsNeeded:
    def test_single_level(self):
        mats = {100: [(34, 2000)]}
        result = _compute_runs_needed(100, {100: 0}, 5, mats, {})
        assert result == {100: 5}

    def test_nested_propagation(self):
        mats = {100: [(200, 10)], 201: [(34, 100)]}
        prods = {200: (201, 1)}
        result = _compute_runs_needed(100, {100: 0, 201: 0}, 3, mats, prods)
        assert result[100] == 3
        # 3 runs of bp 100, each needs 10 of type 200, bp 201 produces 1 per run
        assert result[201] == 30

    def test_with_me_reduction(self):
        mats = {100: [(200, 10)], 201: [(34, 100)]}
        prods = {200: (201, 1)}
        result = _compute_runs_needed(100, {100: 10, 201: 0}, 1, mats, prods)
        assert result[100] == 1
        # ceil(10 * 0.9) = 9 runs of bp 201
        assert result[201] == 9

    def test_blacklist_skips(self):
        mats = {100: [(200, 10), (34, 500)], 201: [(34, 100)]}
        prods = {200: (201, 1)}
        result = _compute_runs_needed(100, {100: 0}, 1, mats, prods, blacklist={200})
        assert result == {100: 1}


# --- _describe_ownership ---


class TestDescribeOwnership:
    def test_bpo_only(self):
        bpo = MagicMock()
        bpo.material_efficiency = 10
        result = _describe_ownership({"bpos": [bpo], "bpcs": []})
        assert result == "BPO (ME 10)"

    def test_bpc_single(self):
        bpc = MagicMock()
        bpc.runs = 50
        result = _describe_ownership({"bpos": [], "bpcs": [bpc]})
        assert result == "1 BPC (50 runs)"

    def test_bpc_multiple(self):
        bpc1 = MagicMock(runs=30)
        bpc2 = MagicMock(runs=20)
        result = _describe_ownership({"bpos": [], "bpcs": [bpc1, bpc2]})
        assert result == "2 BPCs (50 runs)"

    def test_both_bpo_and_bpc(self):
        bpo = MagicMock(material_efficiency=8)
        bpc = MagicMock(runs=25)
        result = _describe_ownership({"bpos": [bpo], "bpcs": [bpc]})
        assert "BPO (ME 8)" in result
        assert "1 BPC (25 runs)" in result
        assert " + " in result

    def test_empty(self):
        result = _describe_ownership({"bpos": [], "bpcs": []})
        assert result is None

    def test_best_bpo_selected(self):
        bpo1 = MagicMock(material_efficiency=5)
        bpo2 = MagicMock(material_efficiency=10)
        result = _describe_ownership({"bpos": [bpo1, bpo2], "bpcs": []})
        assert result == "BPO (ME 10)"
