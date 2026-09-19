"""Unit tests for sim_mch, the Machinist simulator that drives the shipped Lua engine."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim_mch.core import (  # noqa: E402
    BuffWindow, FightConfig, load_tables, rolled_dps, simulate, standard_party_buffs, _aoe_multiplier,
)


class DataTables(unittest.TestCase):
    def test_action_ids_match_the_shipped_lua(self):
        lua_text = (ROOT / "CielMachinist" / "CielMachinist_Data.lua").read_text(encoding="utf-8")
        block = lua_text[lua_text.index("CielMachinistData.Actions = {"):lua_text.index("CielMachinistData.Statuses")]
        lua_ids = {name: int(value) for name, value in re.findall(r"(\w+)\s*=\s*(\d+)", block)}
        for key, data in load_tables()["actions"].items():
            assert key in lua_ids, f"{key} is not in CielMachinistData.Actions"
            assert lua_ids[key] == data["id"], f"{key}: json {data['id']} vs lua {lua_ids[key]}"

    def test_status_ids_match_the_shipped_lua(self):
        lua_text = (ROOT / "CielMachinist" / "CielMachinist_Data.lua").read_text(encoding="utf-8")
        block = lua_text[lua_text.index("CielMachinistData.Statuses = {"):lua_text.index("CielMachinistData.Potions")]
        lua_ids = {name: int(value) for name, value in re.findall(r"(\w+)\s*=\s*(\d+)", block)}
        statuses = load_tables()["statuses"]
        for key, status_id in lua_ids.items():
            assert statuses[key]["id"] == status_id, key

    def test_queen_potency_matches_the_balance(self):
        queen = load_tables()["job"]["queen"]
        per_battery = sum(hit["per_battery"] for hit in queen["hits"])
        assert abs(per_battery - 26.6) < 1e-9, per_battery

    def test_aoe_multiplier(self):
        assert _aoe_multiplier("single", 5) == 1.0
        assert _aoe_multiplier("all", 3) == 3.0
        assert abs(_aoe_multiplier(0.25, 3) - 2.5) < 1e-12
        assert _aoe_multiplier(0.25, 1) == 1.0


class Simulation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tables = load_tables()
        cls.fight = simulate(FightConfig(seconds=180), cls.tables)

    def test_deterministic(self):
        again = simulate(FightConfig(seconds=180), self.tables)
        assert again.to_dict(include_log=True) == self.fight.to_dict(include_log=True)

    def test_duration_and_positive_damage(self):
        assert abs(self.fight.duration_s - 180) < 0.05
        assert self.fight.dps > 0
        assert abs(sum(self.fight.damage_by_action.values()) / self.fight.duration_s - self.fight.dps) < 1e-6

    def test_blazing_shot_gets_the_overheated_bonus(self):
        shot = next(h for h in self.fight.hits if h["name"] == "BlazingShot")
        assert shot["potency"] == 240 + self.tables["job"]["overheated_single_target_bonus"]

    def test_reassemble_and_full_metal_field_are_guaranteed(self):
        assert all(h["crit_mode"] == "guaranteed" for h in self.fight.hits if h["name"] == "FullMetalField")
        sure = [h for h in self.fight.hits if h["crit_mode"] == "guaranteed" and h["name"] != "FullMetalField"]
        assert len(sure) == sum(1 for e in self.fight.log if e["reassembled"])

    def test_wildfire_is_priced_without_crit(self):
        fires = [h for h in self.fight.hits if h["name"] == "Wildfire"]
        assert [h["potency"] for h in fires] == [240 * n for n in self.fight.wildfire_hits[:len(fires)]]
        assert all(h["crit_mode"] == "none" for h in fires)

    def test_queen_damage_scales_with_battery(self):
        first_t, battery = self.fight.queens[0]
        queen = self.tables["job"]["queen"]
        opening = queen["hits"][0]
        hit = next(h for h in self.fight.hits if h["name"] == "Queen: " + opening["name"] and h["t"] > first_t)
        assert abs(hit["potency"] - opening["per_battery"] * battery * queen["potency_scale"]) < 1e-9
        assert abs(hit["t"] - (first_t + opening["offset_s"])) < 1e-6

    def test_party_buffs_raise_damage_only_inside_the_window(self):
        window = BuffWindow(every_s=120, offset_s=6, duration_s=20, mult=1.10)
        assert not window.active(5.9) and window.active(6.0) and window.active(25.9) and not window.active(26.0)
        assert window.active(126.0)
        buffed = simulate(FightConfig(seconds=180, party_buffs=standard_party_buffs(1.10)), self.tables)
        assert buffed.dps > self.fight.dps
        assert [e["name"] for e in buffed.log] == [e["name"] for e in self.fight.log], \
            "party buffs are invisible to the engine and must not change the rotation"

    def test_kill_time_ends_the_fight_and_reaches_the_terminal_band(self):
        result = simulate(FightConfig(seconds=600, kill_time_s=150), self.tables)
        assert abs(result.duration_s - 150) < 0.05
        assert result.stats["heat_left"] < 50, "the terminal band should spend banked heat"

    def test_rolled_dps_is_seeded_and_near_expected(self):
        one = rolled_dps(self.fight, self.tables, 7)
        assert one == rolled_dps(self.fight, self.tables, 7)
        mean = sum(rolled_dps(self.fight, self.tables, seed) for seed in range(200)) / 200
        assert abs(mean / self.fight.dps - 1) < 0.01, (mean, self.fight.dps)

    def test_unknown_engine_setting_is_rejected(self):
        with self.assertRaises(Exception):
            simulate(FightConfig(seconds=5, engine={"notASetting": 1}), self.tables)

    def test_ability_toggle_reaches_the_engine(self):
        result = simulate(FightConfig(seconds=120, engine={"advancedEnabled": True, "abilities.Drill": False}),
                          self.tables)
        assert "Drill" not in result.casts and result.stats["gcd_idle_s"] < 1

    def test_multi_target_switches_to_aoe_actions(self):
        three = simulate(FightConfig(seconds=120, enemies=3), self.tables)
        assert three.casts.get("Scattergun", 0) > 0 and three.casts.get("Bioblaster", 0) > 0
        assert three.casts.get("AutoCrossbow", 0) == 0 and three.casts.get("BlazingShot", 0) > 0
        six = simulate(FightConfig(seconds=120, enemies=6), self.tables)
        assert six.casts.get("AutoCrossbow", 0) > 0 and six.casts.get("BlazingShot", 0) == 0


if __name__ == "__main__":
    unittest.main()
