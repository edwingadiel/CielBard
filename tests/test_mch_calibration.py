"""The parse summariser and the calibration, checked end to end without the network.

A simulated fight is turned into the raw FFLogs shape `mch-analysis/collect.py` caches
(casts, damage, pet damage, ability names), priced with a known scalar and a known share of
auto attacks. Summarising and calibrating it must recover both, and the Queen's timeline.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim_mch import calibrate  # noqa: E402
from sim_mch.core import load_tables  # noqa: E402

_spec = importlib.util.spec_from_file_location("mch_collect", ROOT / "mch-analysis" / "collect.py")
collect = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(collect)

SCALAR = 123.4
AUTO_SHARE = 0.08
START = 5_000_000


def fake_raw(rank: int, seconds: float, tables) -> dict:
    parse = {"duration_s": seconds, "potions": 2}
    fight = calibrate.simulate_parse(parse, tables)
    names = dict(calibrate.NAMES)
    ids = {name: str(1000 + index) for index, name in enumerate(
        list(names.values()) + list(calibrate.QUEEN_COEFFICIENTS) + ["Shot", "Grade 4 Gemdraught of Dexterity"])}
    stamp = lambda t: START + int(round(t * 1000))
    casts = []
    for entry in fight.log:
        if entry["t"] < 0:
            continue
        name = "Grade 4 Gemdraught of Dexterity" if entry["name"] == "Potion" else names.get(entry["name"])
        if name:
            casts.append({"type": "cast", "timestamp": stamp(entry["t"]), "abilityGameID": int(ids[name])})
    medicated = []
    for entry in fight.log:
        if entry["name"] != "Potion":
            continue
        if entry["t"] >= 0:
            medicated.append({"type": "applybuff", "timestamp": stamp(entry["t"])})
        medicated.append({"type": "removebuff", "timestamp": stamp(entry["t"] + 30)})
    damage, pet = [], []
    skill_total = 0.0
    for hit in fight.hits:
        amount = hit["potency"] * hit["factor"] * hit["mult"] * SCALAR
        skill_total += amount
        label = hit["name"].replace(" (DoT)", "")
        if label.startswith("Queen: "):
            pet.append({"type": "damage", "timestamp": stamp(hit["t"]), "amount": amount,
                        "abilityGameID": int(ids[label[len("Queen: "):]])})
        else:
            damage.append({"type": "damage", "timestamp": stamp(hit["t"]), "amount": amount,
                           "abilityGameID": int(ids[names[label]])})
    autos = skill_total * AUTO_SHARE / (1 - AUTO_SHARE)
    damage.append({"type": "damage", "timestamp": stamp(1.0), "amount": autos, "abilityGameID": int(ids["Shot"])})
    # FFLogs also emits 'calculateddamage' previews; they must be ignored.
    damage.append({"type": "calculateddamage", "timestamp": stamp(2.0), "amount": 9e9,
                   "abilityGameID": int(ids["Drill"])})
    return {"rank": rank, "amount": (skill_total + autos) / fight.duration_s, "aDPS": None, "rDPS": None,
            "nDPS": None, "report_code": "synthetic", "fight_id": rank, "start": START,
            "end": stamp(fight.duration_s), "abilities": {v: k for k, v in ids.items()},
            "casts": casts, "damage": damage, "pet_damage": pet, "medicated": medicated}


class Calibration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tables = load_tables()
        cls.parses = [collect.summarise(fake_raw(rank, seconds, cls.tables))
                      for rank, seconds in enumerate((300.0, 420.0, 505.0), start=1)]
        cls.sims = [calibrate.simulate_parse(p, cls.tables) for p in cls.parses]

    def test_summary_has_no_names_and_the_basics(self):
        first = self.parses[0]
        assert "name" not in first and "casts" in first
        # The pre-pull potion has no cast inside the fight; it is counted from its buff.
        assert first["potions"] == 1 and "Grade 4 Gemdraught of Dexterity" not in first["casts"]
        assert self.parses[2]["potions"] == 2, "pre-pull plus the 6:00 burst"
        assert abs(first["duration_s"] - 300) < 0.1
        assert abs(first["auto_attack_share"] - AUTO_SHARE) < 1e-4
        assert first["first_gcds"][:4] == ["Air Anchor", "Drill", "Chain Saw", "Excavator"]
        assert set(first["blazing_per_hypercharge"]) == {5}
        assert all(0 < gap < 1.5 for gap in first["wildfire_minus_hypercharge_s"])

    def test_scalar_is_recovered(self):
        scalar = calibrate.fit_scalar(self.parses, self.sims)
        assert abs(scalar / SCALAR - 1) < 1e-3, scalar

    def test_queen_timeline_is_recovered(self):
        measured = calibrate.queen_timeline(self.parses)
        assumed = self.tables["job"]["queen"]["hits"]
        assert [h["name"] for h in measured] == [h["name"] for h in assumed]
        for got, want in zip(measured, assumed):
            assert abs(got["offset_s"] - want["offset_s"]) < 0.02, (got, want)
        assert abs(sum(h["per_battery"] for h in measured) - 26.6) < 1e-9

    def test_report_builds_and_shows_agreement(self):
        scalar = calibrate.fit_scalar(self.parses, self.sims)
        report = calibrate.build_report(self.parses, self.sims, scalar, calibrate.queen_timeline(self.parses),
                                        self.tables)
        assert "| Drill |" in report and "Automaton Queen hit timeline" in report
        row = next(line for line in report.splitlines() if line.startswith("| Hypercharge |"))
        assert row.rstrip(" |").endswith("+0.0%"), row


if __name__ == "__main__":
    unittest.main()
