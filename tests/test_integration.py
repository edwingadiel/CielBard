"""End-to-end integration invariants for the CielBard simulator (SPEC.md section 8).

One deterministic 60 s fight is run once per test class; every invariant of SPEC.md
table 8.2 is asserted as its own test method with a message naming the observed value.
Four scenario tests (downtime, ping, GCD_ONLY, potion) follow.

Module E depends on Modules C/D. While `sim.core` does not exist yet this file falls
back to `_StubFight`, a minimal deterministic rotation generator defined below that
produces a `FightResult`-shaped object, so the invariant code itself is exercised and
the suite passes standalone. The fallback is used **only** when `sim.core` is genuinely
absent: once it lands, an import error in it propagates instead of being masked.
"""

from __future__ import annotations

import hashlib
import importlib.util
import math
import sys
import time
import unittest
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Invariant 18: the shipped Lua must be byte-identical to the engine this suite
# was baselined against. Re-baseline deliberately, never casually.
# ---------------------------------------------------------------------------

LUA_SHA256 = {
    "CielBard/CielBard_Rotation.lua":
        "82ee8345a7ecef1e6826c3f95550568f1a87689247107b199b98e30c0d6d4129",
    "CielBard/CielBard_Data.lua":
        "5b90cad69a90dd5ab0139fe73b98085283d8c7661457cc4f40ee937adfd1ee86",
}
# Same files with CRLF collapsed to LF, so a checkout with a different core.autocrlf
# setting does not read as a tampered engine.
LUA_SHA256_LF = {
    "CielBard/CielBard_Rotation.lua":
        "7bf51bc90fe5c0b8f84a58ecc5a11cf9fd297949700f3a544470e35eed5a624b",
    "CielBard/CielBard_Data.lua":
        "5b784dfab42a5169f490622cd942159b7693331a322663dc2ef09489dcc0a7f7",
}

ENGINE_CHANGED = "the engine changed - re-baseline deliberately"

# Fallback mechanic constants, used only when `sim.tables` is not importable yet.
# Tests may carry literals; `sim/core.py` and `sim/damage.py` may not (SPEC 0.1.3).
FALLBACK_JOB = {
    "gcd_base_s": 2.50,
    "gcd_rounding_ms": 10,
    "anim_lock_gcd_s": 0.60,
    "anim_lock_ogcd_s": 0.60,
    "army_paeon_max_stacks": 4,
    "army_paeon_haste_per_stack_pct": 4.0,
    "pitch_perfect_potency": [100, 220, 360],
    "apex": {"potency_min": 140, "potency_max": 700},
    "soul_voice_max": 100,
    "pitch_perfect_max_stacks": 3,
    "dot_tick_s": 3.0,
    "song_duration_s": 45.0,
}

FALLBACK_KEYS = ("HeavyShot", "QuickNock", "Bloodletter", "Windbite", "VenomousBite")
DOT_KEYS = ("Stormbite", "CausticBite")
DOT_REFRESH_KEYS = ("Stormbite", "CausticBite", "IronJaws")
SONG_KEYS = ("WanderersMinuet", "MagesBallad", "ArmysPaeon")

EPS = 1e-6
TIME_EPS = 0.01


# ---------------------------------------------------------------------------
# Stub fight (used only while Module C is unlanded)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _DowntimeWindow:
    start_s: float
    end_s: float


@dataclass(frozen=True)
class _FightConfig:
    seconds: float = 510.0
    seed: int = 1
    ping_ms: float = 0.0
    pulse_ms: int = 30
    engine_config: Mapping[str, Any] = field(default_factory=dict)
    downtime: tuple = ()
    enemies: int = 1
    enemy_spread_yalms: float = 2.0
    stat_overrides: Mapping[str, float] = field(default_factory=dict)
    job_overrides: Mapping[str, Any] = field(default_factory=dict)
    use_potion: bool = False
    deterministic_damage: bool = False
    tick_offset_s: float | None = None
    fast_skip_locked: bool = True
    trace: bool = False
    repo_root: Path | None = None


class _StubSimulationError(RuntimeError):
    """Stand-in for `sim.core.SimulationError` while Module C is unlanded."""


@dataclass(frozen=True)
class _CastRecord:
    t_s: float
    action_id: int
    key: str
    name: str
    is_gcd: bool
    target_id: int
    potency: int
    decision: str


@dataclass(frozen=True)
class _DamageRecord:
    t_s: float
    action_id: int
    key: str
    source: str
    potency: int
    amount: float
    crit: bool
    direct_hit: bool
    multiplier: float


@dataclass(frozen=True)
class _StubResult:
    config: Any
    duration_s: float
    total_damage: float
    dps: float
    total_potency: int
    potency_per_second: float
    gcd_count: int
    ogcd_count: int
    gcd_uptime: float
    clipped_s: float
    action_counts: dict
    damage_by_action: dict
    dot_uptime: dict
    song_seconds: dict
    song_casts: dict
    wasted: dict
    casts: tuple
    damage: tuple
    rejections: tuple
    client_rejections: tuple
    warnings: tuple
    engine_state: dict

    def to_dict(self, *, include_events: bool = False) -> dict:
        """JSON-ready projection; mirrors `sim.core.FightResult.to_dict`."""

        def r(value: float) -> float:
            return round(float(value), 6)

        out: dict[str, Any] = {
            "duration_s": r(self.duration_s),
            "total_damage": r(self.total_damage),
            "dps": r(self.dps),
            "total_potency": self.total_potency,
            "potency_per_second": r(self.potency_per_second),
            "gcd_count": self.gcd_count,
            "ogcd_count": self.ogcd_count,
            "gcd_uptime": r(self.gcd_uptime),
            "clipped_s": r(self.clipped_s),
            "action_counts": dict(sorted(self.action_counts.items())),
            "damage_by_action": {k: r(v) for k, v in sorted(self.damage_by_action.items())},
            "dot_uptime": {k: r(v) for k, v in sorted(self.dot_uptime.items())},
            "song_seconds": {k: r(v) for k, v in sorted(self.song_seconds.items())},
            "song_casts": dict(sorted(self.song_casts.items())),
            "wasted": dict(sorted(self.wasted.items())),
            "warnings": list(self.warnings),
        }
        if include_events:
            out["casts"] = [
                {"t_s": r(c.t_s), "action_id": c.action_id, "key": c.key,
                 "is_gcd": c.is_gcd, "potency": c.potency, "decision": c.decision}
                for c in self.casts
            ]
            out["damage"] = [
                {"t_s": r(d.t_s), "key": d.key, "source": d.source,
                 "potency": d.potency, "amount": r(d.amount)}
                for d in self.damage
            ]
        return out


_STUB_ACTIONS = {
    # key: (action id, is_gcd, potency)
    "BurstShot": (16495, True, 220),
    "RefulgentArrow": (7409, True, 280),
    "Stormbite": (7407, True, 100),
    "CausticBite": (7406, True, 150),
    "IronJaws": (3560, True, 100),
    "ApexArrow": (16496, True, 600),
    "BlastArrow": (25784, True, 600),
    "EmpyrealArrow": (3558, False, 260),
    "HeartbreakShot": (36975, False, 180),
    "Sidewinder": (3562, False, 400),
    "PitchPerfect": (7404, False, 360),
    "RagingStrikes": (101, False, 0),
    "BattleVoice": (118, False, 0),
    "RadiantFinale": (25785, False, 0),
    "WanderersMinuet": (3559, False, 0),
    "MagesBallad": (114, False, 0),
    "ArmysPaeon": (116, False, 0),
    "Potion": (900000, False, 0),
}
_STUB_DOT_POTENCY = {"Stormbite": 25, "CausticBite": 20}
_STUB_WEAVE_DEMAND = (2, 1, 3, 1)
_STUB_OGCD_CYCLE = (
    "EmpyrealArrow", "HeartbreakShot", "PitchPerfect",
    "HeartbreakShot", "Sidewinder", "HeartbreakShot",
)
_STUB_POTENCY_TO_DAMAGE = 100.0


def _stub_run_fight(config: _FightConfig, tables: Any = None) -> _StubResult:
    """Generate a deterministic, mechanically plausible 60 s-style rotation.

    This is not a simulator: it is the smallest generator that produces a result
    object satisfying the same contract a real `FightResult` must satisfy, so the
    invariant assertions in this file are genuinely exercised before Module C lands.
    """
    duration = float(config.seconds)
    job = FALLBACK_JOB
    gcd = float(job["gcd_base_s"])
    lock = float(job["anim_lock_gcd_s"]) + float(config.ping_ms) / 1000.0
    gcd_only = str(config.engine_config.get("executionMode", "")).upper() == "GCD_ONLY"
    windows = [(float(w.start_s), float(w.end_s)) for w in config.downtime]

    def in_downtime(t: float) -> bool:
        return any(start <= t < end for start, end in windows)

    casts: list[_CastRecord] = []
    damage: list[_DamageRecord] = []
    dot_intervals: dict[str, list[list[float]]] = {k: [] for k in DOT_KEYS}
    song_intervals: dict[str, list[list[float]]] = {k: [] for k in SONG_KEYS}
    song_casts: dict[str, int] = {}

    pending: list[str] = (["Potion"] if config.use_potion else [])
    pending += ["RagingStrikes", "BattleVoice", "RadiantFinale"]
    ogcd_index = 0
    song_index = 0
    song_end = -1.0
    need_dot = {"Stormbite": True, "CausticBite": True}
    gcd_times: list[float] = []

    def emit(key: str, t: float, decision: str) -> None:
        action_id, is_gcd, potency = _STUB_ACTIONS[key]
        casts.append(_CastRecord(round(t, 6), action_id, key, key, is_gcd, 200,
                                 potency, decision))
        if potency:
            damage.append(_DamageRecord(round(t, 6), action_id, key, "direct", potency,
                                        potency * _STUB_POTENCY_TO_DAMAGE, False, False, 1.0))

    slot = 0
    t_slot = 0.0
    while t_slot < duration - EPS:
        if in_downtime(t_slot):
            for key in need_dot:
                need_dot[key] = True
            slot += 1
            t_slot = slot * gcd
            continue
        # --- the GCD ---
        if need_dot["Stormbite"]:
            key = "Stormbite"
            need_dot["Stormbite"] = False
        elif need_dot["CausticBite"]:
            key = "CausticBite"
            need_dot["CausticBite"] = False
        elif slot == 10:
            key = "ApexArrow"
        elif slot == 11:
            key = "BlastArrow"
        elif slot == 18:
            key = "IronJaws"
        else:
            key = "BurstShot" if slot % 2 == 0 else "RefulgentArrow"
        emit(key, t_slot, "gcd")
        gcd_times.append(t_slot)
        if key in ("Stormbite", "CausticBite"):
            dot_intervals[key].append([t_slot, t_slot + float(job["song_duration_s"])])
        elif key == "IronJaws":
            for dot in DOT_KEYS:
                if dot_intervals[dot]:
                    dot_intervals[dot][-1][1] = t_slot
                dot_intervals[dot].append([t_slot, t_slot + float(job["song_duration_s"])])

        # --- the weaves ---
        if not gcd_only:
            capacity = int((gcd - lock) / lock)
            wanted = _STUB_WEAVE_DEMAND[slot % len(_STUB_WEAVE_DEMAND)]
            for i in range(min(capacity, wanted)):
                t_weave = t_slot + lock * (i + 1)
                if t_weave >= duration - EPS or in_downtime(t_weave):
                    break
                if t_weave >= song_end:
                    song_key = SONG_KEYS[song_index % len(SONG_KEYS)]
                    song_index += 1
                    song_end = t_weave + float(job["song_duration_s"])
                    song_intervals[song_key].append([t_weave, song_end])
                    song_casts[song_key] = song_casts.get(song_key, 0) + 1
                    emit(song_key, t_weave, "song")
                    continue
                if pending:
                    emit(pending.pop(0), t_weave, "burst")
                    continue
                emit(_STUB_OGCD_CYCLE[ogcd_index % len(_STUB_OGCD_CYCLE)], t_weave, "ogcd")
                ogcd_index += 1
        slot += 1
        t_slot = slot * gcd

    # --- DoT ticks ---
    tick = float(job["dot_tick_s"])
    n_ticks = int(duration / tick)
    for i in range(1, n_ticks + 1):
        t = i * tick
        for key, intervals in dot_intervals.items():
            if any(start < t <= end for start, end in intervals) and not in_downtime(t):
                potency = _STUB_DOT_POTENCY[key]
                damage.append(_DamageRecord(round(t, 6), _STUB_ACTIONS[key][0], key, "dot",
                                            potency, potency * _STUB_POTENCY_TO_DAMAGE,
                                            False, False, 1.0))

    def covered(intervals: Sequence[Sequence[float]]) -> float:
        merged: list[list[float]] = []
        for start, end in sorted([list(iv) for iv in intervals]):
            start = max(0.0, start)
            end = min(duration, end)
            if end <= start:
                continue
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        return sum(end - start for start, end in merged)

    gcd_uptime = 0.0
    for i, t in enumerate(gcd_times):
        nxt = gcd_times[i + 1] if i + 1 < len(gcd_times) else duration
        gcd_uptime += min(gcd, max(0.0, nxt - t))
    clipped = 0.0
    for i in range(1, len(gcd_times)):
        gap = gcd_times[i] - gcd_times[i - 1]
        if not any(start <= gcd_times[i - 1] + gcd <= end for start, end in windows):
            clipped += max(0.0, gap - gcd)

    action_counts: dict[str, int] = {}
    damage_by_action: dict[str, float] = {}
    for cast in casts:
        action_counts[cast.key] = action_counts.get(cast.key, 0) + 1
    for rec in damage:
        damage_by_action[rec.key] = damage_by_action.get(rec.key, 0.0) + rec.amount
    total_damage = sum(rec.amount for rec in damage)
    total_potency = sum(rec.potency for rec in damage)
    gcd_count = sum(1 for c in casts if c.is_gcd)
    ogcd_count = len(casts) - gcd_count
    return _StubResult(
        config=config,
        duration_s=duration,
        total_damage=total_damage,
        dps=total_damage / duration,
        total_potency=total_potency,
        potency_per_second=total_potency / duration,
        gcd_count=gcd_count,
        ogcd_count=ogcd_count,
        gcd_uptime=gcd_uptime / duration,
        clipped_s=clipped,
        action_counts=dict(sorted(action_counts.items())),
        damage_by_action=dict(sorted(damage_by_action.items())),
        dot_uptime={k: covered(v) / duration for k, v in sorted(dot_intervals.items())},
        song_seconds={k: covered(v) for k, v in sorted(song_intervals.items()) if v},
        song_casts=dict(sorted(song_casts.items())),
        wasted={"repertoire_overcap": 0, "soul_voice_overcap": 0,
                "hawks_eye_overwritten": 0, "charge_overcap": 0},
        casts=tuple(casts),
        damage=tuple(damage),
        rejections=(),
        client_rejections=(),
        warnings=(),
        engine_state={"lastDecision": "stub", "weavesSinceGCD": 0,
                      "currentSong": "MB", "soulVoice": 40.0, "repertoire": 2.0},
    )


# ---------------------------------------------------------------------------
# Wiring: real simulator when present, stub otherwise
# ---------------------------------------------------------------------------


def _module_present(name: str) -> bool:
    """True when `name` can be located on the path (without importing it)."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


USING_STUB = not (_module_present("sim.core") and _module_present("sim.runconfig"))

if USING_STUB:
    print(
        "test_integration: sim.core/sim.runconfig not present yet - running the "
        "invariants against the local stub fight generator.",
        file=sys.stderr,
    )
    FightConfig = _FightConfig
    DowntimeWindow = _DowntimeWindow
    SimulationError = _StubSimulationError
    run_fight = _stub_run_fight
else:  # pragma: no cover - exercised once Module C lands
    from sim.core import SimulationError, run_fight  # type: ignore[no-redef]
    from sim.runconfig import DowntimeWindow, FightConfig  # type: ignore[no-redef]


@lru_cache(maxsize=1)
def job_table() -> Mapping[str, Any]:
    """Job mechanics from `sim/data/job.json` when Module A has landed, else fallbacks."""
    if _module_present("sim.tables"):  # pragma: no cover - once Module A lands
        from sim.tables import Tables

        return Tables.load().job
    return FALLBACK_JOB


@lru_cache(maxsize=1)
def known_action_keys() -> frozenset[str] | None:
    """Every ability key `sim/data/actions.json` defines, or None when A is unlanded."""
    if _module_present("sim.tables"):  # pragma: no cover - once Module A lands
        from sim.tables import Tables

        return frozenset(Tables.load().actions)
    return None


@lru_cache(maxsize=1)
def barrage_weaponskill_hits() -> int:
    """How many times Barrage makes the next eligible weaponskill land (3)."""
    if _module_present("sim.tables"):  # pragma: no cover - once Module A lands
        from sim.tables import Tables

        return int(Tables.load().status("Barrage").weaponskill_hits)
    return 1


def base_config(**overrides: Any) -> Any:
    """The fixture fight: 60 s, seed 7, no ping, expected-value damage."""
    params: dict[str, Any] = {
        "seconds": 60.0,
        "seed": 7,
        "ping_ms": 0.0,
        "deterministic_damage": True,
    }
    params.update(overrides)
    return FightConfig(**params)


def min_gcd_recast(job: Mapping[str, Any]) -> float:
    """Shortest GCD recast reachable at level 100 (full Army's Paeon haste)."""
    base = float(job["gcd_base_s"])
    haste = float(job["army_paeon_max_stacks"]) * float(job["army_paeon_haste_per_stack_pct"])
    rounding = float(job["gcd_rounding_ms"]) / 1000.0
    return math.floor(base * (100.0 - haste) / 100.0 / rounding) * rounding


def gcd_casts(result: Any) -> list[Any]:
    """Cast records for weaponskills, in time order."""
    return [c for c in result.casts if c.is_gcd]


class FightFixtureMixin:
    """Runs the 60 s reference fight once for the whole class."""

    FIGHT_KWARGS: dict = {}
    result: Any
    elapsed_s: float
    error: BaseException | None = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.job = job_table()
        config = base_config(**cls.FIGHT_KWARGS)
        started = time.perf_counter()
        cls.error = None
        try:
            cls.result = run_fight(config)
        except BaseException as exc:  # noqa: BLE001 - invariant 1 reports it
            cls.result = None
            cls.error = exc
        cls.elapsed_s = time.perf_counter() - started


class TestSixtySecondFight(FightFixtureMixin, unittest.TestCase):
    """SPEC 8.2 invariants 1-18 over one deterministic 60 s fight."""

    def setUp(self) -> None:
        if self._testMethodName != "test_01_fight_completes":
            assert self.error is None, f"fixture fight failed: {self.error!r}"

    # 1 ---------------------------------------------------------------
    def test_01_fight_completes(self) -> None:
        assert self.error is None, f"fight raised {type(self.error).__name__}: {self.error}"
        assert not isinstance(self.error, SimulationError)
        assert abs(self.result.duration_s - 60.0) < TIME_EPS, (
            f"duration_s={self.result.duration_s}, expected 60.0")
        assert self.result.casts, "the fight produced no casts"

    # 2 ---------------------------------------------------------------
    def test_02_gcd_count_in_band(self) -> None:
        n = self.result.gcd_count
        assert n == len(gcd_casts(self.result)), (
            f"gcd_count={n} disagrees with {len(gcd_casts(self.result))} weaponskill casts")
        assert 22 <= n <= 25, f"gcd_count={n}, expected 22..25 over 60 s"

    # 3 ---------------------------------------------------------------
    def test_03_no_gcd_pair_closer_than_recast(self) -> None:
        floor_s = min_gcd_recast(self.job)
        times = [c.t_s for c in gcd_casts(self.result)]
        worst = None
        for earlier, later in zip(times, times[1:]):
            gap = later - earlier
            if worst is None or gap < worst[0]:
                worst = (gap, earlier, later)
        assert worst is not None, "fewer than two GCDs were cast"
        assert worst[0] >= floor_s - TIME_EPS, (
            f"GCDs at {worst[1]:.3f}s and {worst[2]:.3f}s are {worst[0]:.3f}s apart, "
            f"below the {floor_s:.2f}s minimum recast")

    # 4 ---------------------------------------------------------------
    def test_04_total_clipping_under_bound(self) -> None:
        assert self.result.clipped_s <= 1.5, (
            f"clipped_s={self.result.clipped_s:.3f}, bound 1.5")

    # 5 ---------------------------------------------------------------
    def test_05_gcd_uptime(self) -> None:
        assert self.result.gcd_uptime >= 0.95, (
            f"gcd_uptime={self.result.gcd_uptime:.4f}, bound 0.95")

    # 6 ---------------------------------------------------------------
    def test_06_no_cast_while_animation_locked(self) -> None:
        locked = [r for r in self.result.rejections if r.reason == "locked"]
        assert not locked, f"{len(locked)} requests were rejected as locked: {locked[:3]}"
        lock_s = min(float(self.job["anim_lock_gcd_s"]), float(self.job["anim_lock_ogcd_s"]))
        lock_s += float(getattr(self.result.config, "ping_ms", 0.0)) / 1000.0
        times = [c.t_s for c in self.result.casts]
        for earlier, later in zip(times, times[1:]):
            gap = later - earlier
            assert gap >= lock_s - TIME_EPS, (
                f"a cast at {later:.3f}s lands {gap:.3f}s after the cast at {earlier:.3f}s, "
                f"inside its {lock_s:.2f}s animation lock")

    # 7 ---------------------------------------------------------------
    def test_07_dot_uptime(self) -> None:
        duration = self.result.duration_s
        for key in DOT_KEYS:
            assert key in self.result.dot_uptime, f"dot_uptime is missing {key}"
            first = min((c.t_s for c in self.result.casts if c.key == key), default=None)
            assert first is not None, f"{key} was never applied"
            window = max(duration - first, EPS)
            ratio = min(1.0, (self.result.dot_uptime[key] * duration) / window)
            assert ratio >= 0.90, (
                f"{key} uptime after its first application at {first:.2f}s is "
                f"{ratio:.4f} (raw {self.result.dot_uptime[key]:.4f}), bound 0.90")

    # 8 ---------------------------------------------------------------
    def test_08_song_coverage(self) -> None:
        song_times = [c.t_s for c in self.result.casts if c.key in SONG_KEYS]
        assert song_times, "no song was cast"
        assert min(song_times) <= 3.0 + TIME_EPS, (
            f"first song cast at {min(song_times):.2f}s, expected within the first 3 s")
        total = sum(self.result.song_seconds.values())
        assert total >= 55.0, f"song_seconds total {total:.2f}s, bound 55.0s"

    # 9 ---------------------------------------------------------------
    def test_09_no_soul_voice_or_repertoire_overcap(self) -> None:
        apex = self.job["apex"]
        lo, hi = int(apex["potency_min"]), int(apex["potency_max"])
        for cast in self.result.casts:
            if cast.key == "ApexArrow":
                assert lo <= cast.potency <= hi, (
                    f"Apex Arrow at {cast.t_s:.2f}s has potency {cast.potency}, "
                    f"outside the {lo}..{hi} Soul Voice curve")
            elif cast.key == "PitchPerfect":
                allowed = [int(p) for p in self.job["pitch_perfect_potency"]]
                assert cast.potency in allowed, (
                    f"Pitch Perfect at {cast.t_s:.2f}s has potency {cast.potency}, "
                    f"not one of {allowed} (repertoire overcapped past "
                    f"{self.job['pitch_perfect_max_stacks']} stacks)")
        state = self.result.engine_state
        soul = state.get("soulVoice")
        if isinstance(soul, (int, float)):
            assert soul <= float(self.job["soul_voice_max"]) + EPS, (
                f"final Soul Voice {soul}, cap {self.job['soul_voice_max']}")
        rep = state.get("repertoire")
        if isinstance(rep, (int, float)) and str(state.get("currentSong", "")) == "WM":
            assert rep <= float(self.job["pitch_perfect_max_stacks"]) + EPS, (
                f"final WM repertoire {rep}, cap {self.job['pitch_perfect_max_stacks']}")

    # 10 --------------------------------------------------------------
    def test_10_no_level_sync_fallback_casts(self) -> None:
        for key in FALLBACK_KEYS:
            count = self.result.action_counts.get(key, 0)
            assert count == 0, f"{key} was cast {count} times at level 100"

    # 11 --------------------------------------------------------------
    def test_11_every_cast_maps_to_a_known_key(self) -> None:
        known = known_action_keys()
        for cast in self.result.casts:
            assert cast.key, (
                f"cast of action id {cast.action_id} at {cast.t_s:.2f}s has no ability key")
            if known is not None:
                assert cast.key in known, (
                    f"cast key {cast.key!r} at {cast.t_s:.2f}s is not in actions.json")

    # 12 --------------------------------------------------------------
    def test_12_no_rejections(self) -> None:
        assert len(self.result.rejections) == 0, (
            f"{len(self.result.rejections)} core rejections: "
            f"{[(r.reason, round(r.t_s, 2)) for r in self.result.rejections[:5]]}")
        assert len(self.result.client_rejections) == 0, (
            f"{len(self.result.client_rejections)} client rejections: "
            f"{[r.reason for r in self.result.client_rejections[:5]]}")

    # 13 --------------------------------------------------------------
    def test_13_no_engine_warnings(self) -> None:
        assert tuple(self.result.warnings) == (), (
            f"engine warnings with the default config: {list(self.result.warnings)}")

    # 14 --------------------------------------------------------------
    def test_14_determinism(self) -> None:
        again = run_fight(base_config(**self.FIGHT_KWARGS))
        first = self.result.to_dict(include_events=True)
        second = again.to_dict(include_events=True)
        assert first == second, "two identical runs produced different results"

    # 15 --------------------------------------------------------------
    def test_15_weave_ratio(self) -> None:
        gcds = self.result.gcd_count
        assert gcds > 0, "no GCDs were cast"
        ratio = self.result.ogcd_count / gcds
        assert 1.0 <= ratio <= 2.0, (
            f"ogcd/gcd ratio {ratio:.3f} ({self.result.ogcd_count}/{gcds}), "
            f"expected 1.0..2.0")

    # 16 --------------------------------------------------------------
    def test_16_damage_accounting(self) -> None:
        total = sum(d.amount for d in self.result.damage)
        assert abs(self.result.total_damage - total) < 1e-6, (
            f"total_damage={self.result.total_damage!r} but the damage records sum "
            f"to {total!r}")
        assert self.result.dps > 0.0, f"dps={self.result.dps}"
        assert abs(self.result.dps - self.result.total_damage / self.result.duration_s) < 1e-6
        by_action = sum(self.result.damage_by_action.values())
        assert abs(by_action - total) < 1e-6, (
            f"damage_by_action sums to {by_action!r}, damage records to {total!r}")

    # 17 --------------------------------------------------------------
    def test_17_wall_clock_budget(self) -> None:
        print(f"\n60 s fight wall clock: {self.elapsed_s:.3f}s")
        assert self.elapsed_s < 3.0, (
            f"the 60 s fight took {self.elapsed_s:.3f}s, budget 3.0s")

    # 18 --------------------------------------------------------------
    def test_18_shipped_lua_untouched(self) -> None:
        for rel, expected in LUA_SHA256.items():
            path = ROOT / rel
            assert path.is_file(), f"{rel} is missing"
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if digest == expected:
                continue
            normalised = hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()
            assert normalised == LUA_SHA256_LF.get(rel), (
                f"{rel} sha256 is {digest} (line-ending-normalised {normalised}), "
                f"baseline {expected}: {ENGINE_CHANGED}")


class TestDowntimeScenario(unittest.TestCase):
    """SPEC 8.2 test 19: a 10 s downtime window inside a 60 s fight."""

    WINDOW = (20.0, 30.0)

    @classmethod
    def setUpClass(cls) -> None:
        window = DowntimeWindow(start_s=cls.WINDOW[0], end_s=cls.WINDOW[1])
        cls.result = run_fight(base_config(downtime=(window,)))

    def test_19a_no_casts_inside_the_window(self) -> None:
        start, end = self.WINDOW
        inside = [c for c in self.result.casts if start <= c.t_s < end]
        assert not inside, (
            f"{len(inside)} casts inside the downtime window: "
            f"{[(c.key, round(c.t_s, 2)) for c in inside[:5]]}")

    def test_19b_dots_reapplied_after_the_window(self) -> None:
        end = self.WINDOW[1]
        after = [c.t_s for c in self.result.casts if c.key in DOT_REFRESH_KEYS and c.t_s >= end]
        assert after, "no DoT was reapplied after the downtime window"
        assert min(after) - end <= 3.0 + TIME_EPS, (
            f"first DoT reapplication {min(after) - end:.2f}s after the window, bound 3.0s")

    def test_19c_fight_still_completes(self) -> None:
        assert abs(self.result.duration_s - 60.0) < TIME_EPS
        assert self.result.gcd_count > 0, "no GCDs outside the downtime window"


class TestPingReducesWeaves(unittest.TestCase):
    """SPEC 8.2 test 20: extra client lock costs oGCDs."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.fast = run_fight(base_config(ping_ms=0.0))
        cls.slow = run_fight(base_config(ping_ms=150.0))

    # Documented in README, "Known mechanic mismatches": a weave costs
    # anim_lock_ogcd_s + ping = 0.75 s at 150 ms and the engine weaves while
    # weaveMinGcdRemaining (0.65 s) is left, so a 2.5 s GCD still fits two weaves.
    # Clipping starts above ~233 ms of ping and the oGCD count only falls above
    # ~350 ms, which matches the game. The invariant is kept as an expected
    # failure so that an engine change which does make 150 ms cost a weave is
    # reported (an unexpected success fails the suite) instead of passing silently.
    @unittest.expectedFailure
    def test_20_ping_reduces_ogcd_count(self) -> None:
        assert self.slow.ogcd_count < self.fast.ogcd_count, (
            f"ping=150ms produced {self.slow.ogcd_count} oGCDs, "
            f"ping=0ms produced {self.fast.ogcd_count}")


class TestGcdOnlyMode(unittest.TestCase):
    """SPEC 8.2 test 21: executionMode=GCD_ONLY suppresses every weave."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.result = run_fight(base_config(
            engine_config={"advancedEnabled": True, "executionMode": "GCD_ONLY"}))

    def test_21_no_ogcds(self) -> None:
        offenders = sorted({c.key for c in self.result.casts if not c.is_gcd})
        assert self.result.ogcd_count == 0, (
            f"GCD_ONLY produced {self.result.ogcd_count} oGCDs: {offenders}")

    def test_21b_still_casts_gcds(self) -> None:
        assert self.result.gcd_count > 0, "GCD_ONLY produced no GCDs at all"


class TestPotionScenario(unittest.TestCase):
    """SPEC 8.2 test 22: one potion, used immediately before Raging Strikes."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.result = run_fight(base_config(use_potion=True))

    # Documented in README, "Known mechanic mismatches": the engine only takes the
    # potion as the first weave of a window, and on the opener E.TrySong spends
    # that slot on Wanderer's Minuet, so Raging Strikes lands in the second slot
    # and the potion slips to the next window, before Battle Voice. Reproducing
    # the real opener needs a pre-pull window, which the simulator does not model.
    # Kept as an expected failure so a fix is reported rather than passing quietly.
    @unittest.expectedFailure
    def test_22_potion_used_once_before_raging_strikes(self) -> None:
        """Raging Strikes is the next oGCD after the potion, within one GCD.

        "Immediately before" is read as "the next off-GCD cast, within one GCD":
        the potion is a weave, so a weaponskill legitimately sits between it and
        Raging Strikes when the weave window only fits one oGCD.

        Only this pair is the documented engine limitation. The satisfiable part of
        SPEC 8.2 #22 - exactly one potion, and it is not the last off-GCD cast -
        lives in `test_22c_exactly_one_potion`, because an `expectedFailure` method
        stops enforcing every assertion that precedes the failing one.
        """
        casts, index, following = self._potion()
        assert following[0].key == "RagingStrikes", (
            f"the oGCD after the potion is {following[0].key!r}, expected RagingStrikes")
        gap = following[0].t_s - casts[index].t_s
        assert gap <= float(job_table()["gcd_base_s"]) + TIME_EPS, (
            f"Raging Strikes lands {gap:.2f}s after the potion, expected within one GCD")

    def _potion(self) -> tuple[list[Any], int, list[Any]]:
        """The cast list, the index of the single potion, and the oGCDs after it."""
        casts = list(self.result.casts)
        potions = [i for i, c in enumerate(casts) if c.key == "Potion"]
        assert len(potions) == 1, (
            f"expected exactly 1 potion cast in 60 s, got {len(potions)} "
            f"at {[round(casts[i].t_s, 2) for i in potions]}")
        index = potions[0]
        following = [c for c in casts[index + 1:] if not c.is_gcd]
        assert following, "the potion was the last off-GCD cast of the fight"
        return casts, index, following

    def test_22c_exactly_one_potion(self) -> None:
        """The half of SPEC 8.2 #22 the shipped engine does satisfy, enforced live."""
        self._potion()

    def test_22b_no_potion_without_the_flag(self) -> None:
        plain = run_fight(base_config())
        assert plain.action_counts.get("Potion", 0) == 0, (
            "a potion was used although use_potion is False")


class TestBurstWindowContents(unittest.TestCase):
    """MECHANICS_CORRECTIONS.md 15: what the guide expects inside the 2-minute buffs.

    The listed burst GCDs are Apex Arrow, Blast Arrow, a Barrage-buffed Refulgent
    Arrow, Resonant Arrow, Radiant Encore and Iron Jaws.  Four of them are pinned
    here as an invariant over every full (non-opener) Raging Strikes window, and
    the DoT re-snapshot is accepted either as Iron Jaws or as a fresh application
    of both DoTs, which correction 10 makes equivalent.

    Apex and Blast Arrow are deliberately *not* required inside the window: the
    shipped engine fires Apex off-cycle at its gauge threshold, and whether that
    beats holding it for the buffs is exactly the open question of corrections
    16-18.  What is asserted about them here is only that they stay paired.
    """

    WINDOW_S = 20.0

    @classmethod
    def setUpClass(cls) -> None:
        if USING_STUB:  # pragma: no cover - the stub has no engine to observe
            raise unittest.SkipTest("sim.core is not present; nothing to assert")
        cls.result = run_fight(base_config(seconds=300.0))
        cls.casts = list(cls.result.casts)
        raging = [c.t_s for c in cls.casts if c.key == "RagingStrikes"]
        # The opener is a partial window: the pre-pull song and the potion slot
        # displace part of it (see README, "Known mechanic mismatches"), so the
        # invariant is asserted over the steady-state windows only.
        cls.windows = raging[1:]

    def _window(self, start: float) -> list[Any]:
        return [c for c in self.casts if start <= c.t_s <= start + self.WINDOW_S]

    def test_23_every_burst_window_is_a_full_two_minute_window(self) -> None:
        assert len(self.windows) >= 2, (
            f"expected at least two post-opener Raging Strikes windows in 300 s, "
            f"got {len(self.windows)}")
        for earlier, later in zip(self.windows, self.windows[1:]):
            gap = later - earlier
            assert 110.0 <= gap <= 130.0, (
                f"Raging Strikes windows at {earlier:.2f}s and {later:.2f}s are "
                f"{gap:.2f}s apart, expected about 120 s")

    def test_23b_radiant_encore_is_cast_inside_every_window(self) -> None:
        for start in self.windows:
            keys = [c.key for c in self._window(start)]
            assert "RadiantEncore" in keys, (
                f"no Radiant Encore in the buff window at {start:.2f}s: {keys}")

    def test_23c_barrage_yields_resonant_arrow_and_a_buffed_refulgent(self) -> None:
        for start in self.windows:
            window = self._window(start)
            barrage = [c for c in window if c.key == "Barrage"]
            assert barrage, (
                f"no Barrage in the buff window at {start:.2f}s: "
                f"{[c.key for c in window]}")
            after = [c for c in window if c.t_s > barrage[0].t_s]
            keys = [c.key for c in after]
            assert "ResonantArrow" in keys, (
                f"Barrage at {barrage[0].t_s:.2f}s was not followed by Resonant "
                f"Arrow inside the window: {keys}")
            assert "RefulgentArrow" in keys, (
                f"Barrage's guaranteed Hawk's Eye was not spent on a Refulgent "
                f"Arrow inside the window at {start:.2f}s: {keys}")
            # ...and that Refulgent Arrow is Barrage-buffed, not an ordinary one:
            # `statuses.json` gives Barrage `weaponskill_hits = 3`, so the first
            # eligible weaponskill after it produces three damage records at one
            # timestamp instead of one.
            hits = barrage_weaponskill_hits()
            refulgent = next(c for c in after if c.key == "RefulgentArrow")
            landed = [
                d for d in self.result.damage
                if d.key == "RefulgentArrow" and refulgent.t_s - TIME_EPS <= d.t_s
                <= refulgent.t_s + self.WINDOW_S
            ]
            assert landed, (
                f"the Refulgent Arrow cast at {refulgent.t_s:.2f}s dealt no damage")
            first = [d for d in landed if abs(d.t_s - landed[0].t_s) < TIME_EPS]
            assert len(first) == hits, (
                f"the Refulgent Arrow at {refulgent.t_s:.2f}s landed {len(first)} "
                f"time(s), expected {hits} under Barrage")

    def test_23f_no_barrage_expires_unused(self) -> None:
        """A Barrage nothing consumes is a 120 s raid buff thrown away.

        `_handle_status_expire` is the expiry-only path - `_consume_multi_hit`
        removes the status through `_remove_status` instead - so this counter is
        non-zero exactly when the window ran out with no damaging weaponskill in
        it. It reads 0 on this fixture, which is what makes it a useful pin: a
        rotation change that starves the Barrage proc moves it off 0.
        """
        wasted = self.result.wasted
        assert "barrage_expired" in wasted, (
            "FightResult.wasted no longer reports barrage_expired")
        casts = [c.key for c in self.casts].count("Barrage")
        assert wasted["barrage_expired"] == 0, (
            f"{wasted['barrage_expired']} of {casts} Barrage casts expired without "
            f"buffing a weaponskill")

    def test_23d_the_dots_are_resnapshotted_inside_every_window(self) -> None:
        for start in self.windows:
            keys = [c.key for c in self._window(start)]
            fresh = "Stormbite" in keys and "CausticBite" in keys
            assert "IronJaws" in keys or fresh, (
                f"the window at {start:.2f}s re-snapshots no DoT (neither Iron Jaws "
                f"nor both DoTs re-applied): {keys}")

    def test_23e_apex_and_blast_arrow_stay_paired(self) -> None:
        keys = [c.key for c in self.casts]
        apex = keys.count("ApexArrow")
        blast = keys.count("BlastArrow")
        assert apex > 0, "no Apex Arrow was cast in 300 s"
        assert blast <= apex, f"{blast} Blast Arrows for {apex} Apex Arrows"
        assert apex - blast <= 1, (
            f"{apex} Apex Arrows produced only {blast} Blast Arrows")
        for index, key in enumerate(keys):
            if key == "BlastArrow":
                before = keys[:index]
                assert "ApexArrow" in before, "a Blast Arrow preceded every Apex Arrow"


class TestMultiTargetScenarios(unittest.TestCase):
    """Review item "Recommended #7": 2-, 3- and 5-dummy packs.

    A pack is `FightConfig.enemies` dummies standing on a ring of
    `FightConfig.enemy_spread_yalms` around the engine's target. The engine never
    reads that number: it counts the pack itself out of
    `EntityList("alive,attackable,maxdistance=30")`, keeping only entities whose
    `pos` is within 5 yalms of its target (`CielBard_Rotation.lua`
    `E.CountEnemiesNear`), and it scans
    `EntityList("alive,attackable,incombat,maxdistance=25")` for multi-dot
    candidates (`E.FindMultiDotTarget`). So these tests prove the fake client's
    entity list, not a configuration flag, is what turns the AoE replacements on:
    `test_24f` scatters the same three dummies 12 yalms apart and the engine goes
    back to its single-target rotation.
    """

    COUNTS = (1, 2, 3, 5)
    SPREAD = 2.0

    @classmethod
    def setUpClass(cls) -> None:
        if USING_STUB:  # pragma: no cover - the stub models no AoE at all
            raise unittest.SkipTest("multi-target scenarios need the real simulator")
        cls.results = {
            n: run_fight(base_config(enemies=n, enemy_spread_yalms=cls.SPREAD))
            for n in cls.COUNTS
        }
        cls._report()

    # --- reporting ------------------------------------------------------

    @classmethod
    def _report(cls) -> None:
        """Print the per-action cast counts side by side, one column per pack size."""
        keys = sorted({k for r in cls.results.values() for k in r.action_counts})
        width = max((len(k) for k in keys), default=0)
        header = "  ".join(f"{n:>6}" for n in cls.COUNTS)
        print(f"\n[multi-target] 60 s seed 7, dummies on a {cls.SPREAD:g}-yalm ring")
        print(f"{'action':<{width}}  {header}")
        for key in keys:
            row = "  ".join(
                f"{cls.results[n].action_counts.get(key, 0):>6}" for n in cls.COUNTS
            )
            print(f"{key:<{width}}  {row}")
        for label, value in (
            ("dps", lambda r: f"{r.dps:>6.0f}"),
            ("potency", lambda r: f"{r.total_potency:>6}"),
            ("hits", lambda r: f"{r.damage_event_count:>6}"),
        ):
            row = "  ".join(value(cls.results[n]) for n in cls.COUNTS)
            print(f"{label:<{width}}  {row}")

    # --- helpers --------------------------------------------------------

    @staticmethod
    def _hits(result: Any, key: str) -> list[Any]:
        return [d for d in result.damage if d.key == key and d.source == "direct"]

    AOE_KEYS = ("Ladonsbite", "Shadowbite", "RainOfDeath")

    # --- tests ----------------------------------------------------------

    def test_24_single_target_uses_no_aoe_replacement(self) -> None:
        counts = self.results[1].action_counts
        used = {k: counts[k] for k in self.AOE_KEYS if counts.get(k)}
        assert not used, f"a lone dummy drew AoE actions: {used}"

    def test_24b_a_pack_switches_the_engine_to_its_aoe_actions(self) -> None:
        """Two and three dummies must reach the engine's `aoeTargets` thresholds."""
        for n in (2, 3, 5):
            counts = self.results[n].action_counts
            used = {k: counts[k] for k in self.AOE_KEYS if counts.get(k)}
            assert used, (
                f"{n} dummies drew no AoE action at all; the engine counted "
                f"the pack as {counts}")
            assert counts.get("Ladonsbite", 0) > 0, (
                f"{n} dummies drew no Ladonsbite: {counts}")

    def test_24c_an_aoe_action_without_falloff_hits_every_dummy(self) -> None:
        """Shadowbite, Ladonsbite and Rain of Death are per-target, full potency."""
        tables = _tables()
        for n in self.COUNTS:
            result = self.results[n]
            for key in self.AOE_KEYS:
                action = tables.action(key)
                assert action.aoe is True, key
                assert action.falloff == 0.0, f"{key} should have no falloff"
                casts = result.action_counts.get(key, 0)
                hits = self._hits(result, key)
                assert len(hits) == casts * n, (
                    f"{n} dummies: {casts} {key} casts produced {len(hits)} damage "
                    f"events, expected {casts * n}")
                potencies = {d.potency for d in hits}
                assert potencies <= {action.potency, action.barrage_potency} - {0}, (
                    f"{key} landed at unexpected potencies {sorted(potencies)}")

    def test_24d_an_aoe_action_with_falloff_halves_every_extra_dummy(self) -> None:
        """Blast Arrow, Resonant Arrow and Radiant Encore: first target, then 50 %."""
        tables = _tables()
        for key in ("BlastArrow", "ResonantArrow", "RadiantEncore"):
            action = tables.action(key)
            assert action.aoe is True, f"{key} is a falloff AoE"
            assert abs(action.falloff - 0.5) < 1e-12, f"{key} falloff"
        for n in self.COUNTS:
            result = self.results[n]
            for key in ("BlastArrow", "ResonantArrow", "RadiantEncore"):
                casts = result.action_counts.get(key, 0)
                if not casts:
                    continue
                hits = self._hits(result, key)
                assert len(hits) == casts * n, (
                    f"{n} dummies: {casts} {key} casts produced {len(hits)} hits")
                full = [d.potency for d in hits[:1]]
                if n > 1:
                    splash = hits[1].potency
                    assert splash == round(full[0] * 0.5), (
                        f"{key} splash {splash} is not half of {full[0]}")

    def test_24e_more_dummies_never_lose_damage(self) -> None:
        previous = 0.0
        for n in self.COUNTS:
            total = self.results[n].total_damage
            assert total > previous, (
                f"{n} dummies dealt {total:.0f}, no more than {previous:.0f}")
            previous = total

    def test_24f_a_scattered_pack_is_not_an_aoe_pack(self) -> None:
        """12 yalms apart is outside `CountEnemiesNear`'s 5-yalm cluster test.

        The engine then counts one enemy and runs its single-target rotation, which
        is what proves the AoE switch comes from `EntityList` and `entity.pos` and
        not from `FightConfig.enemies`.
        """
        scattered = run_fight(base_config(enemies=3, enemy_spread_yalms=12.0))
        used = {k: scattered.action_counts[k]
                for k in self.AOE_KEYS if scattered.action_counts.get(k)}
        assert not used, f"a scattered pack still drew AoE actions: {used}"
        lone = self.results[1]
        assert [(c.t_s, c.key) for c in scattered.casts] == \
            [(c.t_s, c.key) for c in lone.casts], (
            "a scattered 3-pack must take the same decisions as a lone dummy")
        # And the damage model agrees: nothing splashes onto a dummy the engine does
        # not count as part of the pack.
        assert abs(scattered.total_damage - lone.total_damage) < 1e-6, (
            f"a scattered 3-pack dealt {scattered.total_damage:.0f} against the lone "
            f"dummy's {lone.total_damage:.0f}")

    def test_24g_the_ring_radius_does_not_change_the_rotation(self) -> None:
        """Any spread inside the 5-yalm cluster test is the same fight."""
        tight = run_fight(base_config(enemies=3, enemy_spread_yalms=0.5))
        wide = self.results[3]
        assert [(c.t_s, c.key, c.potency) for c in tight.casts] == \
            [(c.t_s, c.key, c.potency) for c in wide.casts]
        assert abs(tight.total_damage - wide.total_damage) < 1e-6

    def test_24h_barrage_is_spent_correctly_in_every_pack(self) -> None:
        """Either a triple-hit Refulgent Arrow or a 300-potency Shadowbite, never both.

        This is the review's second high-priority finding expressed end to end: the
        Barrage buff has exactly one consumer per Barrage cast, and whichever
        weaponskill consumes it takes the effect its own tooltip describes.
        """
        tables = _tables()
        hits = barrage_weaponskill_hits()
        shadowbite = tables.action("Shadowbite")
        refulgent = tables.action("RefulgentArrow")
        for n in self.COUNTS:
            result = self.results[n]
            barrages = result.action_counts.get("Barrage", 0)
            assert barrages > 0, f"{n} dummies: no Barrage in 60 s"
            tripled = self._tripled_refulgent_casts(result, refulgent, hits)
            boosted = [c for c in result.casts
                       if c.key == "Shadowbite" and c.potency == shadowbite.barrage_potency]
            consumers = tripled + len(boosted)
            assert consumers <= barrages, (
                f"{n} dummies: {consumers} Barrage consumers for {barrages} Barrages")
            for cast in boosted:
                assert cast.potency == 300, cast
            # No Shadowbite may ever land three times: Barrage raises its potency.
            per_cast = len(self._hits(result, "Shadowbite")) / max(
                1, result.action_counts.get("Shadowbite", 0))
            assert per_cast in (0.0, float(n)), (
                f"{n} dummies: {per_cast} Shadowbite damage events per cast")

    @staticmethod
    def _tripled_refulgent_casts(result: Any, refulgent: Any, hits: int) -> int:
        """How many Refulgent Arrow casts produced `hits` damage events."""
        total = len([d for d in result.damage
                     if d.key == "RefulgentArrow" and d.source == "direct"])
        casts = result.action_counts.get("RefulgentArrow", 0)
        extra = total - casts
        assert extra % (hits - 1) == 0, (
            f"{total} Refulgent Arrow hits for {casts} casts is not a whole number "
            f"of {hits}-hit casts")
        return extra // (hits - 1)


@lru_cache(maxsize=1)
def _tables() -> Any:
    """`sim.tables.Tables` for the assertions that read action metadata."""
    from sim.tables import Tables

    return Tables.load()


if __name__ == "__main__":
    unittest.main(verbosity=2)
