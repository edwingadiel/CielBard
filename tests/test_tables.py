"""Unit tests for `sim.tables` (SPEC.md section 4.8).

Written pytest-style (plain `assert`) inside `unittest.TestCase` subclasses so the file
runs under both `pytest` and `python -m unittest discover`.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sim.tables import (  # noqa: E402
    SimDataError,
    Tables,
    apex_potency,
    gcd_recast,
)

DATA_DIR = _REPO_ROOT / "sim" / "data"

EXPECTED_ACTIONS = (
    "HeavyShot",
    "BurstShot",
    "RefulgentArrow",
    "Stormbite",
    "CausticBite",
    "IronJaws",
    "ApexArrow",
    "BlastArrow",
    "ResonantArrow",
    "RadiantEncore",
    "Ladonsbite",
    "Shadowbite",
    "QuickNock",
    "EmpyrealArrow",
    "Sidewinder",
    "HeartbreakShot",
    "Bloodletter",
    "RainOfDeath",
    "PitchPerfect",
    "Barrage",
    "RagingStrikes",
    "BattleVoice",
    "RadiantFinale",
    "WanderersMinuet",
    "MagesBallad",
    "ArmysPaeon",
    "SecondWind",
    "Troubadour",
    "NaturesMinne",
    "WardensPaean",
    "Windbite",
    "VenomousBite",
    "Potion",
)

EXPECTED_STATUSES = (
    "Stormbite",
    "CausticBite",
    "Windbite",
    "VenomousBite",
    "HawksEye",
    "RagingStrikes",
    "BattleVoice",
    "RadiantFinale",
    "BlastArrowReady",
    "ResonantArrowReady",
    "RadiantEncoreReady",
    "Barrage",
    "WanderersMinuet",
    "MagesBallad",
    "ArmysPaeon",
    "ArmysMuse",
    "ArmysEthos",
    "Medicated",
)


def _copy_data(destination: Path) -> Path:
    """Copy the shipped data directory into `destination` so a test can mutate it."""
    target = destination / "data"
    shutil.copytree(DATA_DIR, target)
    return target


def _patch_json(path: Path, mutate) -> None:
    """Load `path`, hand the parsed object to `mutate`, write it back."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


class LoadTests(unittest.TestCase):
    """Loading and validating the shipped tables."""

    def test_load_default_tables(self) -> None:
        tables = Tables.load()
        for key in EXPECTED_ACTIONS:
            assert key in tables.actions, f"actions.json is missing {key}"
        for key in EXPECTED_STATUSES:
            assert key in tables.statuses, f"statuses.json is missing {key}"
        assert len(tables.actions) == len(EXPECTED_ACTIONS)
        assert len(tables.statuses) == len(EXPECTED_STATUSES)

        burst = tables.action("BurstShot")
        assert burst.id == 16495
        assert burst.potency == 220
        assert burst.is_gcd is True
        assert burst.grants[0].status == "HawksEye"
        assert abs(burst.grants[0].chance - 0.35) < 1e-12

        heartbreak = tables.action("HeartbreakShot")
        assert heartbreak.max_charges == 3
        assert abs(heartbreak.recast_s - 15.0) < 1e-12
        assert abs(heartbreak.cooldown_s - 45.0) < 1e-12

        assert tables.by_id(16495) is burst
        assert tables.by_id(1234567) is None
        assert tables.status_by_id(1201).key == "Stormbite"
        assert tables.status("Stormbite").dot_potency == 25
        assert tables.status("CausticBite").dot_potency == 20

        assert abs(float(tables.job["gcd_base_s"]) - 2.5) < 1e-12
        assert abs(float(tables.stats["crit_mult"]) - 1.60) < 1e-12

    def test_ids_match_shipped_lua(self) -> None:
        tables = Tables.load()
        problems = tables.verify_against_lua(_REPO_ROOT)
        assert problems == [], "id drift vs CielBard_Data.lua: " + "; ".join(problems)

    def test_unknown_status_in_grants_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = _copy_data(Path(tmp))

            def mutate(payload: dict) -> None:
                payload["BurstShot"]["grants"] = [{"status": "NoSuchStatus"}]

            _patch_json(data_dir / "actions.json", mutate)
            try:
                Tables.load(data_dir)
            except SimDataError as exc:
                assert "NoSuchStatus" in str(exc)
            else:
                raise AssertionError("expected SimDataError for an unknown granted status")

    def test_unknown_status_in_requires_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = _copy_data(Path(tmp))

            def mutate(payload: dict) -> None:
                payload["RefulgentArrow"]["requires"] = ["NotAStatus"]

            _patch_json(data_dir / "actions.json", mutate)
            try:
                Tables.load(data_dir)
            except SimDataError as exc:
                assert "NotAStatus" in str(exc)
            else:
                raise AssertionError("expected SimDataError for an unknown required status")

    def test_unknown_record_key_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = _copy_data(Path(tmp))

            def mutate(payload: dict) -> None:
                payload["BurstShot"]["potenccy"] = 220

            _patch_json(data_dir / "actions.json", mutate)
            try:
                Tables.load(data_dir)
            except SimDataError as exc:
                assert "potenccy" in str(exc)
            else:
                raise AssertionError("expected SimDataError for an unknown record key")

    def test_duplicate_action_id_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = _copy_data(Path(tmp))

            def mutate(payload: dict) -> None:
                payload["Sidewinder"]["id"] = payload["BurstShot"]["id"]

            _patch_json(data_dir / "actions.json", mutate)
            try:
                Tables.load(data_dir)
            except SimDataError as exc:
                assert "duplicate action id" in str(exc)
            else:
                raise AssertionError("expected SimDataError for a duplicate action id")

    def test_negative_potency_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = _copy_data(Path(tmp))

            def mutate(payload: dict) -> None:
                payload["BurstShot"]["potency"] = -1

            _patch_json(data_dir / "actions.json", mutate)
            try:
                Tables.load(data_dir)
            except SimDataError as exc:
                assert "negative" in str(exc)
            else:
                raise AssertionError("expected SimDataError for a negative potency")

    def test_legacy_repertoire_requires_dot_job_file_still_loads(self) -> None:
        """A job.json carrying only the superseded key is accepted (SPEC 4.4).

        `sim/core.py` reads `repertoire_requires_dot` as the inverse of
        `repertoire_independent_of_dots`; that path is only reachable if the loader
        does not demand the new key outright.
        """
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = _copy_data(Path(tmp))

            def mutate(payload: dict) -> None:
                del payload["repertoire_independent_of_dots"]
                payload["repertoire_requires_dot"] = True

            _patch_json(data_dir / "job.json", mutate)
            tables = Tables.load(data_dir)
            assert tables.job["repertoire_requires_dot"] is True
            assert "repertoire_independent_of_dots" not in tables.job

    def test_job_file_without_either_repertoire_dot_key_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = _copy_data(Path(tmp))

            def mutate(payload: dict) -> None:
                del payload["repertoire_independent_of_dots"]

            _patch_json(data_dir / "job.json", mutate)
            try:
                Tables.load(data_dir)
            except SimDataError as exc:
                assert "repertoire_independent_of_dots" in str(exc)
            else:
                raise AssertionError("expected SimDataError for the missing key")

    def test_barrage_carries_the_weaponskill_hit_count(self) -> None:
        tables = Tables.load()
        assert tables.status("Barrage").weaponskill_hits == 3
        assert tables.status("HawksEye").weaponskill_hits == 1
        assert tables.action("RefulgentArrow").multi_hit_eligible is True
        assert tables.action("ResonantArrow").multi_hit_eligible is False

    def test_multi_hit_eligible_on_a_non_gcd_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = _copy_data(Path(tmp))

            def mutate(payload: dict) -> None:
                payload["HeartbreakShot"]["multi_hit_eligible"] = True

            _patch_json(data_dir / "actions.json", mutate)
            try:
                Tables.load(data_dir)
            except SimDataError as exc:
                assert "multi_hit_eligible" in str(exc)
            else:
                raise AssertionError("expected SimDataError for an oGCD marked eligible")

    def test_missing_file_raises_simdataerror(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = _copy_data(Path(tmp))
            (data_dir / "job.json").unlink()
            try:
                Tables.load(data_dir)
            except SimDataError as exc:
                assert "job.json" in str(exc)
            else:
                raise AssertionError("expected SimDataError for a missing data file")

    def test_action_lookup_error_names_the_key(self) -> None:
        tables = Tables.load()
        try:
            tables.action("NotAnAbility")
        except KeyError as exc:
            assert "NotAnAbility" in str(exc)
        else:
            raise AssertionError("expected KeyError for an unknown action key")


class CurveTests(unittest.TestCase):
    """The derived curves Module A owns."""

    def test_apex_potency_curve(self) -> None:
        job = Tables.load().job
        assert apex_potency(20, job) == 100
        assert apex_potency(60, job) == 350
        assert apex_potency(80, job) == 475
        assert apex_potency(100, job) == 600
        # Clamped outside the documented range.
        assert apex_potency(0, job) == 100
        assert apex_potency(140, job) == 600

    def test_gcd_haste_rounding(self) -> None:
        assert abs(gcd_recast(2.5, 0) - 2.50) < 1e-9
        assert abs(gcd_recast(2.5, 4) - 2.40) < 1e-9
        assert abs(gcd_recast(2.5, 16) - 2.10) < 1e-9
        # Truncation, not rounding: 2.5 * 0.88 = 2.20; 2.5 * 0.99 = 2.475 -> 2.47.
        assert abs(gcd_recast(2.5, 12) - 2.20) < 1e-9
        assert abs(gcd_recast(2.5, 1) - 2.47) < 1e-9

    def test_gcd_recast_uses_job_table(self) -> None:
        tables = Tables.load()
        assert abs(tables.gcd_recast(0.0) - 2.50) < 1e-9
        haste = 4 * float(tables.job["army_paeon_haste_per_stack_pct"])
        assert abs(tables.gcd_recast(haste) - 2.10) < 1e-9

    def test_radiant_encore_and_coda_tables_indexable_by_coda_count(self) -> None:
        job = Tables.load().job
        coda = job["coda_damage_mult"]
        encore = job["radiant_encore_potency"]
        assert len(coda) == 4
        assert len(encore) == 4
        assert coda[0] == 1.0
        assert abs(coda[1] - 1.02) < 1e-12
        assert abs(coda[2] - 1.04) < 1e-12
        assert abs(coda[3] - 1.06) < 1e-12
        assert encore[0] == 0
        assert encore[1] == 700
        assert encore[2] == 800
        assert encore[3] == 1100
        for count in range(4):
            assert coda[count] >= 1.0
            assert encore[count] >= 0


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
