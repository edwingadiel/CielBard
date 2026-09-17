"""One test per numbered item of `sim/MECHANICS_CORRECTIONS.md`.

The corrections override SPEC.md where the two disagree, so this file is the
place that pins them: items 1-12 against the simulator core and the data tables,
item 15 against a real fight (`tests/test_integration.py` owns the SPEC 8.2
end-to-end invariants; the burst-window composition check lives there).

Items 13 and 14 are engine-configuration guidance (`CielBard/` is never edited by
the simulator, so they are sweep inputs, not simulator behaviour) and items 16-18
are open investigations, so neither group is asserted here.

Written pytest-style (plain `assert`) inside `unittest.TestCase` subclasses, like
the rest of `tests/`, so the file runs under plain `unittest` discovery.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sim.core import PLAYER, Simulation  # noqa: E402
from sim.damage import BuffSnapshot  # noqa: E402
from sim.events import ACTION_EXECUTE, SERVER_TICK  # noqa: E402
from sim.runconfig import FightConfig, SimConfigError  # noqa: E402
from sim.tables import Tables  # noqa: E402

US = 1_000_000
TABLES = Tables.load()
JOB = TABLES.job


def _queued(simulation: Simulation) -> list:
    """Every event still on the queue (white-box: `EventQueue` exposes no listing)."""
    return list(simulation.queue._heap)


def _sim(**overrides: object) -> Simulation:
    """A Simulation built but not run, for white-box tests of the state machine."""
    values: dict = {
        "seconds": 120.0,
        "seed": 7,
        "deterministic_damage": True,
        "tick_offset_s": 1.5,
        "repo_root": _REPO_ROOT,
    }
    values.update(overrides)
    return Simulation(FightConfig(**values), TABLES)


# ---------------------------------------------------------------------------
# 1. Repertoire timing
# ---------------------------------------------------------------------------
class RepertoireTimingTests(unittest.TestCase):
    """Item 1: 80 % every 3 s on the song timer, nothing in the final 3 s."""

    def test_rolls_sit_on_the_song_timer_grid(self) -> None:
        simulation = _sim()
        simulation._start_song("WM", 0)
        step_us = int(round(float(JOB["server_tick_s"]) * US))
        song_us = int(round(float(JOB["song_duration_s"]) * US))
        ticks = sorted(
            event.t_us for event in _queued(simulation)
            if event.kind == SERVER_TICK and event.payload.get("scope") == "song"
        )
        assert ticks == list(range(step_us, song_us - step_us + 1, step_us)), ticks
        remaining = [(song_us - t) / US for t in ticks]
        assert len(ticks) == 14, ticks
        assert remaining[0] == 42.0 and remaining[-1] == 3.0, remaining

    def test_no_proc_in_the_final_three_seconds(self) -> None:
        simulation = _sim()
        simulation._start_song("MB", 0)
        song_us = int(round(float(JOB["song_duration_s"]) * US))
        cutoff_us = song_us - int(round(float(JOB["server_tick_s"]) * US))
        late = [
            event.t_us for event in _queued(simulation)
            if event.kind == SERVER_TICK and event.payload.get("scope") == "song"
            and event.t_us > cutoff_us
        ]
        assert late == [], f"Repertoire rolls scheduled inside the last 3 s: {late}"

    def test_roll_chance_is_eighty_percent(self) -> None:
        assert abs(float(JOB["repertoire_proc_chance"]) - 0.80) < 1e-12
        simulation = _sim()
        simulation.song = "MB"
        procs = sum(1 for _ in range(2000) if simulation._repertoire_proc(0))
        assert 1540 <= procs <= 1660, procs

    def test_procs_are_independent_of_dots_by_default(self) -> None:
        assert JOB["repertoire_independent_of_dots"] is True
        assert JOB["repertoire_on_song_timer"] is True
        assert JOB["repertoire_skip_final_tick"] is True
        simulation = _sim()
        assert simulation._repertoire_independent_of_dots is True
        simulation.song = "MB"
        assert not simulation._any_dot_on_target()
        assert any(simulation._repertoire_proc(0) for _ in range(200))

    def test_dot_independence_is_a_flag_that_can_be_turned_off(self) -> None:
        simulation = _sim(job_overrides={"repertoire_independent_of_dots": False})
        assert simulation._repertoire_independent_of_dots is False
        simulation.song = "MB"
        assert not simulation._any_dot_on_target()
        assert not any(simulation._repertoire_proc(0) for _ in range(400))
        simulation._apply_status(
            simulation.target_id, "Stormbite", 0, snapshot=BuffSnapshot()
        )
        assert any(simulation._repertoire_proc(0) for _ in range(40))

    def test_legacy_requires_dot_key_is_still_honoured(self) -> None:
        """`None` deletes the new key, which is what a legacy job.json looks like."""
        legacy = _sim(job_overrides={
            "repertoire_independent_of_dots": None,
            "repertoire_requires_dot": True,
        })
        assert legacy._repertoire_independent_of_dots is False

    def test_a_misspelled_job_override_is_rejected(self) -> None:
        """The flag the docs point at must not fail silently on a typo."""
        try:
            _sim(job_overrides={"repertoire_independant_of_dots": False})
        except SimConfigError as exc:
            assert "repertoire_independant_of_dots" in str(exc)
        else:
            raise AssertionError("expected SimConfigError for an unknown override key")

    def test_a_job_override_gets_the_data_file_type_checks(self) -> None:
        try:
            _sim(job_overrides={"repertoire_independent_of_dots": "false"})
        except SimConfigError as exc:
            assert "boolean" in str(exc)
        else:
            raise AssertionError("expected SimConfigError for a non-boolean override")
        try:
            _sim(job_overrides={"repertoire_proc_chance": 1.5})
        except SimConfigError as exc:
            assert "outside [0, 1]" in str(exc)
        else:
            raise AssertionError("expected SimConfigError for an out-of-range override")

    def test_core_only_job_keys_stay_overridable(self) -> None:
        """`potion_hqid` and friends are read with in-code defaults, not from job.json."""
        simulation = _sim(job_overrides={"potion_hqid": 4242})
        assert simulation._potion_hqid == 4242

    def test_a_full_song_produces_procs_without_any_dot(self) -> None:
        """End to end: no DoT is ever applied, the song still feeds the gauge."""
        simulation = _sim()
        simulation._start_song("AP", 0)
        t = 0
        while t <= 45 * US:
            for event in simulation.queue.pop_due(t):
                if event.kind == SERVER_TICK and event.payload.get("scope") == "song":
                    simulation._handle(event)
            t += simulation.pulse_us
        assert simulation.soul_voice > 0
        assert simulation.paeon_stacks > 0


# ---------------------------------------------------------------------------
# 2-4. Empyreal Arrow, Soul Voice, the Mage's Ballad refund
# ---------------------------------------------------------------------------
class ProcEffectTests(unittest.TestCase):
    """Items 2, 3 and 4."""

    def test_02_empyreal_arrow_is_a_guaranteed_proc(self) -> None:
        simulation = _sim()
        simulation._start_song("WM", 0)
        data = TABLES.action("EmpyrealArrow")
        for _ in range(3):
            simulation._apply_special(
                "EmpyrealArrow", data, 1 * US, simulation.target_id, BuffSnapshot()
            )
        assert simulation.repertoire == 3
        assert simulation.soul_voice == 3 * int(JOB["soul_voice_per_repertoire"])

    def test_03_five_soul_voice_per_proc_in_every_song(self) -> None:
        per_proc = int(JOB["soul_voice_per_repertoire"])
        assert per_proc == 5
        for code in ("WM", "MB", "AP"):
            simulation = _sim()
            simulation._start_song(code, 0)
            for index in range(4):
                simulation._repertoire_proc(1 * US, guaranteed=True)
                assert simulation.soul_voice == per_proc * (index + 1), (code, index)

    def test_03b_an_overcapped_stack_still_pays_soul_voice(self) -> None:
        simulation = _sim()
        simulation._start_song("WM", 0)
        for _ in range(5):
            simulation._repertoire_proc(1 * US, guaranteed=True)
        assert simulation.repertoire == 3
        assert simulation.wasted_procs["repertoire_overcap"] == 2
        assert simulation.soul_voice == 25

    def test_04_ballad_proc_refunds_half_a_heartbreak_charge(self) -> None:
        assert abs(float(JOB["ballad_charge_reduction_s"]) - 7.5) < 1e-12
        simulation = _sim()
        simulation._start_song("MB", 0)
        simulation._set_charge_progress(0, 0.0)
        simulation._repertoire_proc(0, guaranteed=True)
        assert abs(simulation._charge_progress_s(0) - 7.5) < 1e-6
        assert simulation.charges(0) == 0
        simulation._repertoire_proc(0, guaranteed=True)
        assert abs(simulation._charge_progress_s(0) - 15.0) < 1e-6
        assert simulation.charges(0) == 1
        assert simulation.ballad_procs == 2


# ---------------------------------------------------------------------------
# 5-6. Army's Paeon, Army's Muse, Pitch Perfect
# ---------------------------------------------------------------------------
class HasteAndStackTests(unittest.TestCase):
    """Items 5 and 6."""

    def test_05_paeon_stacks_are_four_percent_each_up_to_four(self) -> None:
        assert int(JOB["army_paeon_max_stacks"]) == 4
        assert abs(float(JOB["army_paeon_haste_per_stack_pct"]) - 4.0) < 1e-12
        simulation = _sim()
        simulation._start_song("AP", 0)
        seen = []
        for _ in range(6):
            simulation._repertoire_proc(0, guaranteed=True)
            seen.append(simulation._haste_pct())
        assert simulation.paeon_stacks == 4
        assert seen == [4.0, 8.0, 12.0, 16.0, 16.0, 16.0], seen

    def test_05b_muse_is_twelve_percent_for_ten_seconds_at_full_stacks(self) -> None:
        assert list(JOB["army_muse_haste_by_stacks_pct"]) == [1.0, 2.0, 4.0, 12.0]
        assert TABLES.status("ArmysMuse").duration_s == 10.0
        simulation = _sim()
        simulation._start_song("AP", 0)
        for _ in range(4):
            simulation._repertoire_proc(0, guaranteed=True)
        simulation._start_song("WM", 10 * US)
        muse = simulation.player_statuses.get("ArmysMuse")
        assert muse is not None, "the song after Army's Paeon did not gain Army's Muse"
        assert muse.stacks == 4
        assert abs(simulation._haste_pct() - 12.0) < 1e-12
        assert (muse.expires_us - 10 * US) / US == 10.0
        simulation._remove_status(PLAYER, "ArmysMuse", 20 * US)
        assert simulation._haste_pct() == 0.0

    def test_05c_muse_haste_by_stack_count(self) -> None:
        for stacks, pct in enumerate([1.0, 2.0, 4.0, 12.0], start=1):
            simulation = _sim()
            simulation._start_song("AP", 0)
            for _ in range(stacks):
                simulation._repertoire_proc(0, guaranteed=True)
            simulation._start_song("MB", 10 * US)
            assert abs(simulation._haste_pct() - pct) < 1e-12, (stacks, pct)

    def test_05d_muse_needs_army_s_paeon_first(self) -> None:
        simulation = _sim()
        simulation._start_song("MB", 0)
        for _ in range(4):
            simulation._repertoire_proc(0, guaranteed=True)
        simulation._start_song("WM", 10 * US)
        assert "ArmysMuse" not in simulation.player_statuses
        assert simulation._haste_pct() == 0.0

    def test_06_repertoire_caps_at_three_and_pitch_perfect_spends_it(self) -> None:
        assert int(JOB["pitch_perfect_max_stacks"]) == 3
        assert list(JOB["pitch_perfect_potency"]) == [100, 220, 360]
        simulation = _sim()
        simulation._start_song("WM", 0)
        for _ in range(10):
            simulation._repertoire_proc(0, guaranteed=True)
        assert simulation.repertoire == 3
        data = TABLES.action("PitchPerfect")
        assert simulation._potency_for("PitchPerfect", data) == 360
        simulation._apply_special(
            "PitchPerfect", data, 0, simulation.target_id, BuffSnapshot()
        )
        assert simulation.repertoire == 0


# ---------------------------------------------------------------------------
# 7-9. Hawk's Eye, Barrage, Radiant Encore
# ---------------------------------------------------------------------------
class ProcSourceAndWindowTests(unittest.TestCase):
    """Items 7, 8 and 9."""

    HAWKS_EYE_SOURCES = ("BurstShot", "Stormbite", "CausticBite", "IronJaws", "Ladonsbite")

    def test_07_every_listed_source_grants_hawks_eye_at_the_job_rate(self) -> None:
        assert abs(float(JOB["hawks_eye_proc_chance"]) - 0.35) < 1e-12
        for key in self.HAWKS_EYE_SOURCES:
            data = TABLES.action(key)
            grants = [g for g in data.grants if g.status == "HawksEye"]
            assert grants, f"{key} does not grant Hawk's Eye"
            assert abs(grants[0].chance - 0.35) < 1e-12, key
            simulation = _sim()
            hits = 0
            for _ in range(2000):
                simulation._remove_status(PLAYER, "HawksEye", 0)
                simulation._apply_grants(data, 0, simulation.target_id, BuffSnapshot())
                hits += int(simulation._has("HawksEye"))
            assert 620 <= hits <= 780, (key, hits)

    def test_07b_barrage_grants_hawks_eye_every_single_time(self) -> None:
        simulation = _sim()
        data = TABLES.action("Barrage")
        for _ in range(200):
            simulation._remove_status(PLAYER, "HawksEye", 0)
            simulation._apply_grants(data, 0, simulation.target_id, BuffSnapshot())
            assert simulation._has("HawksEye"), "Barrage's Hawk's Eye must be guaranteed"

    def test_07c_the_job_rate_moves_every_proc_source_but_not_barrage(self) -> None:
        simulation = _sim(job_overrides={"hawks_eye_proc_chance": 0.0})
        for key in self.HAWKS_EYE_SOURCES:
            simulation._remove_status(PLAYER, "HawksEye", 0)
            for _ in range(50):
                simulation._apply_grants(
                    TABLES.action(key), 0, simulation.target_id, BuffSnapshot()
                )
            assert not simulation._has("HawksEye"), key
        simulation._apply_grants(
            TABLES.action("Barrage"), 0, simulation.target_id, BuffSnapshot()
        )
        assert simulation._has("HawksEye"), "the proc rate must not gate Barrage"

    def test_07d_hawks_eye_enables_refulgent_arrow_for_thirty_seconds(self) -> None:
        assert TABLES.status("HawksEye").duration_s == 30.0
        refulgent = TABLES.action("RefulgentArrow")
        assert refulgent.potency == 280
        assert "HawksEye" in refulgent.requires
        assert "HawksEye" in TABLES.action("Shadowbite").requires
        simulation = _sim()
        simulation._apply_status(PLAYER, "HawksEye", 2 * US)
        assert (simulation.player_statuses["HawksEye"].expires_us - 2 * US) / US == 30.0

    def test_08_barrage_opens_a_thirty_second_resonant_arrow_window(self) -> None:
        # Item 8's 30 s is the Resonant Arrow window, which `ResonantArrowReady`
        # carries. The Barrage buff itself is the live 10 s triple-hit window.
        assert TABLES.status("ResonantArrowReady").duration_s == 30.0
        assert TABLES.status("Barrage").duration_s == 10.0
        resonant = TABLES.action("ResonantArrow")
        assert resonant.potency == 600
        assert resonant.aoe is True
        assert abs(resonant.falloff - 0.45) < 1e-12, "55 % falloff leaves a 0.45 share"
        simulation = _sim()
        simulation._apply_grants(
            TABLES.action("Barrage"), 5 * US, simulation.target_id, BuffSnapshot()
        )
        ready = simulation.player_statuses["ResonantArrowReady"]
        assert (ready.expires_us - 5 * US) / US == 30.0
        assert (simulation.player_statuses["Barrage"].expires_us - 5 * US) / US == 10.0

    def test_08b_resonant_arrow_splashes_at_forty_five_percent(self) -> None:
        simulation = _sim(enemies=2, stat_overrides={"crit_rate": 0.0, "dh_rate": 0.0})
        simulation._apply_status(PLAYER, "ResonantArrowReady", 0)
        simulation.queue.push_kind(
            0, ACTION_EXECUTE, key="ResonantArrow", action_id=36976,
            target_id=simulation.target_id, potency=600,
        )
        for event in simulation.queue.pop_due(0):
            simulation._handle(event)
        hits = [d for d in simulation.damage_events if d.key == "ResonantArrow"]
        assert [d.potency for d in hits] == [600, 270], hits

    @staticmethod
    def _execute(simulation: Simulation, key: str, t_us: int = 0) -> list:
        """Run one ACTION_EXECUTE for `key` and return the damage records it made."""
        action = TABLES.action(key)
        before = len(simulation.damage_events)
        simulation.queue.push_kind(
            t_us, ACTION_EXECUTE, key=key, action_id=action.id,
            target_id=simulation.target_id, potency=action.potency,
        )
        for event in simulation.queue.pop_due(t_us):
            simulation._handle(event)
        return list(simulation.damage_events[before:])

    def test_08c_barrage_triples_the_next_eligible_weaponskill(self) -> None:
        """Barrage's own effect: Refulgent Arrow lands three times (280 -> 840)."""
        assert TABLES.status("Barrage").weaponskill_hits == 3
        simulation = _sim(stat_overrides={"crit_rate": 0.0, "dh_rate": 0.0})
        simulation._apply_status(PLAYER, "Barrage", 0)
        simulation._apply_status(PLAYER, "HawksEye", 0)
        hits = self._execute(simulation, "RefulgentArrow")
        assert [d.potency for d in hits] == [280, 280, 280], hits
        assert "Barrage" not in simulation.player_statuses, "Barrage was not consumed"
        again = self._execute(simulation, "BurstShot", 3 * US)
        assert [d.potency for d in again] == [220], again

    def test_08d_an_ineligible_weaponskill_neither_triples_nor_eats_barrage(self) -> None:
        """Resonant Arrow is cast between Barrage and Refulgent; it must not spend it."""
        assert TABLES.action("ResonantArrow").multi_hit_eligible is False
        assert TABLES.action("RefulgentArrow").multi_hit_eligible is True
        simulation = _sim(stat_overrides={"crit_rate": 0.0, "dh_rate": 0.0})
        simulation._apply_status(PLAYER, "Barrage", 0)
        simulation._apply_status(PLAYER, "ResonantArrowReady", 0)
        resonant = self._execute(simulation, "ResonantArrow")
        assert [d.potency for d in resonant] == [600], resonant
        assert "Barrage" in simulation.player_statuses
        heartbreak = self._execute(simulation, "HeartbreakShot", 1 * US)
        assert [d.potency for d in heartbreak] == [180], "an oGCD must not spend Barrage"
        assert "Barrage" in simulation.player_statuses

    def test_08e_barrage_multiplies_the_aoe_splash_too(self) -> None:
        simulation = _sim(enemies=2, stat_overrides={"crit_rate": 0.0, "dh_rate": 0.0})
        simulation._apply_status(PLAYER, "Barrage", 0)
        simulation._apply_status(PLAYER, "HawksEye", 0)
        hits = self._execute(simulation, "Shadowbite")
        assert [d.potency for d in hits] == [200, 200] * 3, hits

    def test_09_radiant_encore_potency_is_700_800_1100(self) -> None:
        assert list(JOB["radiant_encore_potency"]) == [0, 700, 800, 1100]
        finale = TABLES.action("RadiantFinale")
        encore = TABLES.action("RadiantEncore")
        for count, potency in ((1, 700), (2, 800), (3, 1100)):
            simulation = _sim()
            for code in ("WM", "MB", "AP")[:count]:
                simulation._start_song(code, 0)
            simulation._apply_special(
                "RadiantFinale", finale, 0, simulation.target_id, BuffSnapshot()
            )
            assert simulation._potency_for("RadiantEncore", encore) == potency, count
            instance = simulation.player_statuses["RadiantFinale"]
            assert abs(instance.mult_override - (1.0 + 0.02 * count)) < 1e-9, count

    def test_09b_radiant_finale_opens_a_thirty_second_encore_window(self) -> None:
        assert TABLES.status("RadiantEncoreReady").duration_s == 30.0
        simulation = _sim()
        simulation._start_song("WM", 0)
        simulation._apply_special(
            "RadiantFinale", TABLES.action("RadiantFinale"), 4 * US,
            simulation.target_id, BuffSnapshot(),
        )
        ready = simulation.player_statuses["RadiantEncoreReady"]
        assert (ready.expires_us - 4 * US) / US == 30.0


# ---------------------------------------------------------------------------
# 10-12. Iron Jaws, the charge pool, the burst buffs
# ---------------------------------------------------------------------------
class DotRefreshAndCooldownTests(unittest.TestCase):
    """Items 10, 11 and 12."""

    def test_10_iron_jaws_is_a_fresh_application_of_both_dots(self) -> None:
        simulation = _sim(stat_overrides={"crit_rate": 0.0, "dh_rate": 0.0})
        clean = simulation._snapshot()
        for key in ("Stormbite", "CausticBite"):
            simulation._apply_status(simulation.target_id, key, 0, snapshot=clean)
        simulation._apply_status(PLAYER, "RagingStrikes", 30 * US)
        simulation._iron_jaws(30 * US, simulation.target_id, simulation._snapshot())
        holder = simulation.entity_statuses[simulation.target_id]
        for key in ("Stormbite", "CausticBite"):
            instance = holder[key]
            duration_s = (instance.expires_us - 30 * US) / US
            assert duration_s == TABLES.status(key).duration_s, (key, duration_s)
            assert abs(instance.snapshot.damage_mult - 1.15) < 1e-9, key
        simulation._tick_dots(33 * US)
        ticks = [d for d in simulation.damage_events if d.source == "dot"]
        assert len(ticks) == 2
        assert all(abs(d.multiplier - 1.15) < 1e-9 for d in ticks), ticks

    def test_10b_iron_jaws_never_applies_a_dot_that_is_not_there(self) -> None:
        simulation = _sim()
        simulation._apply_status(
            simulation.target_id, "Stormbite", 0, snapshot=BuffSnapshot()
        )
        simulation._iron_jaws(3 * US, simulation.target_id, BuffSnapshot())
        holder = simulation.entity_statuses[simulation.target_id]
        assert "CausticBite" not in holder, "Iron Jaws applied a DoT the target lacked"
        assert TABLES.action("IronJaws").potency == 100

    def test_11_heartbreak_shot_is_three_charges_of_fifteen_seconds(self) -> None:
        data = TABLES.action("HeartbreakShot")
        assert data.max_charges == 3
        assert abs(data.recast_s - 15.0) < 1e-12
        assert abs(data.cooldown_s - 45.0) < 1e-12
        simulation = _sim()
        assert simulation._charge_max == 3
        assert abs(simulation._charge_recast_s - 15.0) < 1e-12
        assert abs(simulation._charge_cap_s - 45.0) < 1e-12
        for seconds, expected in ((0.0, 0), (14.9, 0), (15.0, 1), (30.0, 2), (45.0, 3)):
            simulation._set_charge_progress(0, seconds)
            assert simulation.charges(0) == expected, (seconds, expected)

    def test_12_battle_voice_radiant_finale_and_raging_strikes_last_twenty(self) -> None:
        for key in ("RagingStrikes", "BattleVoice", "RadiantFinale"):
            assert TABLES.status(key).duration_s == 20.0, key
        simulation = _sim()
        for key in ("RagingStrikes", "BattleVoice", "RadiantFinale"):
            simulation._apply_status(PLAYER, key, 7 * US)
            duration_s = (simulation.player_statuses[key].expires_us - 7 * US) / US
            assert duration_s == 20.0, (key, duration_s)

    def test_12b_a_burst_buff_expires_on_schedule(self) -> None:
        simulation = _sim()
        simulation._apply_status(PLAYER, "BattleVoice", 0)
        t = 0
        while t <= 21 * US:
            for event in simulation.queue.pop_due(t):
                simulation._handle(event)
            t += simulation.pulse_us
        assert not simulation._has("BattleVoice")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
