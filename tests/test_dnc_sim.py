"""Unit tests for sim_dnc, the Dancer simulator that drives the shipped Lua engine."""

from __future__ import annotations

import importlib.util
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim_dnc import calibrate  # noqa: E402
from sim_dnc.core import FightConfig, load_tables, simulate, standard_party_buffs  # noqa: E402

_spec = importlib.util.spec_from_file_location("dnc_collect", ROOT / "dnc-analysis" / "collect.py")
collect = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(collect)

STEPS = ("Emboite", "Entrechat", "Jete", "Pirouette")


class DataTables(unittest.TestCase):
    def test_ids_match_the_shipped_lua(self):
        lua_text = (ROOT / "CielDancer" / "CielDancer_Data.lua").read_text(encoding="utf-8")
        actions = lua_text[lua_text.index("CielDancerData.Actions = {"):lua_text.index("CielDancerData.Statuses")]
        statuses = lua_text[lua_text.index("CielDancerData.Statuses = {"):lua_text.index("CielDancerData.Potions")]
        lua_actions = {n: int(v) for n, v in re.findall(r"(\w+)\s*=\s*(\d+)", actions)}
        lua_statuses = {n: int(v) for n, v in re.findall(r"(\w+)\s*=\s*(\d+)", statuses)}
        tables = load_tables()
        for key, data in tables["actions"].items():
            assert lua_actions.get(key) == data["id"], key
        for key, status_id in lua_statuses.items():
            assert tables["statuses"][key]["id"] == status_id, key

    def test_every_weaponskill_is_in_the_engines_gcd_set(self):
        lua_text = (ROOT / "CielDancer" / "CielDancer_Data.lua").read_text(encoding="utf-8")
        block = lua_text[lua_text.index("CielDancerData.GCD = {"):lua_text.index("CielDancerData.StandardFinishIDs")]
        gcd_ids = {int(v) for v in re.findall(r"\[(\d+)\]", block)}
        for key, data in load_tables()["actions"].items():
            assert (data["id"] in gcd_ids) == bool(data.get("gcd")), key


class Simulation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tables = load_tables()
        cls.fight = simulate(FightConfig(seconds=200, seed=5), cls.tables)

    def test_same_seed_same_fight_and_other_seed_other_fight(self):
        again = simulate(FightConfig(seconds=200, seed=5), self.tables)
        assert again.to_dict(include_log=True) == self.fight.to_dict(include_log=True)
        other = simulate(FightConfig(seconds=200, seed=6), self.tables)
        assert [e["name"] for e in other.log] != [e["name"] for e in self.fight.log]

    def test_step_sequences_are_random_and_never_wrong(self):
        dances = []
        current = None
        for entry in self.fight.log:
            if entry["name"] in ("StandardStep", "TechnicalStep"):
                current = []
                dances.append((entry["name"], current))
            elif entry["name"] in STEPS and current is not None:
                current.append(entry["name"])
        assert all(len(steps) == (2 if kind == "StandardStep" else 4) for kind, steps in dances), dances
        assert all(len(set(steps)) == len(steps) for _, steps in dances), "steps never repeat within a dance"
        assert len({tuple(steps) for _, steps in dances}) > 1, "sequences differ between dances"
        assert self.fight.stats["wrong_steps"] == 0

    def test_dance_gcds_run_at_their_own_recast(self):
        log = [e for e in self.fight.log if e["gcd"]]
        for first, second in zip(log, log[1:]):
            gap = round(second["t"] - first["t"], 2)
            if first["name"] in STEPS:
                assert abs(gap - 1.0) < 0.07, (first["name"], gap)
            elif first["name"].endswith("Finish") or first["name"].endswith("Step"):
                assert abs(gap - 1.5) < 0.07, (first["name"], gap)

    def test_buffs_are_priced(self):
        finish = next(h for h in self.fight.hits if h["name"] == "QuadrupleTechnicalFinish")
        tillana = next(h for h in self.fight.hits if h["name"] == "Tillana" and h["t"] > finish["t"])
        assert abs(tillana["mult"] - 1.05 * 1.05) < 1e-9, "Standard and Technical Finish stack multiplicatively"
        starfall = next(h for h in self.fight.hits if h["name"] == "StarfallDance")
        stats = self.tables["stats"]
        assert abs(starfall["factor"] - stats["crit_mult"] * stats["dh_mult"]) < 1e-9
        plain = next(h for h in self.fight.hits if h["name"] == "Cascade" and h["t"] > 40 and h["t"] < 100)
        assert tillana["factor"] > plain["factor"], "Devilment raises crit and direct-hit rates"

    def test_solo_dummy_generates_less_esprit(self):
        solo = simulate(FightConfig(seconds=200, seed=5, partner=False, party_size=1), self.tables)
        assert solo.casts.get("SaberDance", 0) < self.fight.casts.get("SaberDance", 0)

    def test_party_buffs_do_not_change_the_rotation(self):
        buffed = simulate(FightConfig(seconds=200, seed=5, party_buffs=standard_party_buffs(1.10)), self.tables)
        assert buffed.dps > self.fight.dps
        assert [e["name"] for e in buffed.log] == [e["name"] for e in self.fight.log]

    def test_unknown_engine_setting_is_rejected(self):
        with self.assertRaises(Exception):
            simulate(FightConfig(seconds=5, engine={"notASetting": 1}), self.tables)

    def test_kill_time_dumps_resources(self):
        result = simulate(FightConfig(seconds=600, kill_time_s=170, seed=2), self.tables)
        assert abs(result.duration_s - 170) < 0.05
        # Feathers are pooled for the burst and must be gone at the kill. Esprit is not asserted: an
        # ally can feed the gauge after the last weaponskill, and which seed that happens on is luck.
        assert result.stats["feathers_left"] <= 1, result.stats
        kept = simulate(FightConfig(seconds=600, kill_time_s=170, seed=2, engine={"terminalDumping": False}), self.tables)
        assert kept.casts.get("FanDance", 0) <= result.casts.get("FanDance", 0)


class Summary(unittest.TestCase):
    def test_summarise_a_synthetic_parse(self):
        tables = load_tables()
        fight = calibrate.simulate_parse({"duration_s": 300.0, "potions": 1}, tables, seed=3)
        names = {k: v for k, v in calibrate.NAMES.items()}
        names.update({"DoubleStandardFinish": "Double Standard Finish",
                      "QuadrupleTechnicalFinish": "Quadruple Technical Finish", **{s: s for s in STEPS}})
        ids = {name: str(2000 + i) for i, name in enumerate(list(names.values()) + ["Attack"])}
        start = 7_000_000
        stamp = lambda t: start + int(round(t * 1000))
        casts, damage, total = [], [], 0.0
        for entry in fight.log:
            if entry["t"] >= 0 and entry["name"] in names:
                casts.append({"type": "cast", "timestamp": stamp(entry["t"]), "abilityGameID": int(ids[names[entry["name"]]])})
                if entry["name"] == "QuadrupleTechnicalFinish":  # FFLogs logs the party application too
                    casts.append({"type": "cast", "timestamp": stamp(entry["t"] + 0.5), "abilityGameID": int(ids[names[entry["name"]]])})
        for hit in fight.hits:
            amount = hit["potency"] * hit["factor"] * hit["mult"] * 100
            total += amount
            damage.append({"type": "damage", "timestamp": stamp(hit["t"]), "amount": amount,
                           "abilityGameID": int(ids[names[hit["name"]]])})
        damage.append({"type": "damage", "timestamp": stamp(1), "amount": total / 9, "abilityGameID": int(ids["Attack"])})
        raw = {"rank": 1, "amount": 1.0, "report_code": "synthetic", "fight_id": 1, "start": start,
               "end": stamp(fight.duration_s), "abilities": {v: k for k, v in ids.items()},
               "casts": casts, "damage": damage, "pet_damage": [],
               "medicated": [{"type": "removebuff", "timestamp": stamp(28.9), "sourceID": 3, "targetID": 3}]}
        summary = collect.summarise(raw)
        assert summary["potions"] == 1, "a pre-pull potion is counted from its buff"
        assert abs(summary["auto_attack_share"] - 0.1) < 1e-3
        assert summary["casts"]["Quadruple Technical Finish"] == fight.casts["QuadrupleTechnicalFinish"], \
            "the doubled finish log entry is collapsed"
        assert summary["steps"] == sum(fight.casts.get(s, 0) for s in STEPS) - 2, "pre-pull steps are outside the fight"
        assert summary["opener"][:3] == ["Double Standard Finish", "Technical Step", "Quadruple Technical Finish"]
        assert summary["burst_gcds"][0][:2] == ["Tillana", "Dance of the Dawn"]
        assert "name" not in summary


if __name__ == "__main__":
    unittest.main()
