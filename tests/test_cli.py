"""Tests for the simulator's runner and CLI layer (SPEC.md section 7.6).

The tests run against the real `sim` package when module C (`sim/core.py`) has landed.
While it has not, they build a minimal stub package in a temporary directory - a copy of
module D's own files plus stand-ins for `sim/__init__.py`, `sim/runconfig.py`,
`sim/core.py`, `sim/client.py` and `sim/tables.py` - so this file passes standalone and
keeps exercising the real CLI code paths, including the subprocess entry points.

Written pytest-style (plain `assert`) inside `unittest.TestCase` classes so both runners
work.
"""

from __future__ import annotations

import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OWNED_FILES = ("report.py", "run.py", "batch.py", "sweep.py", "calibrate.py")
FAST = os.environ.get("CIELBARD_SIM_FAST") == "1"

STUB_INIT = '''"""CielBard simulator: drives the shipped CielBard Lua engine over a
modelled fight."""

__version__ = "1.0.0"
ENGINE_VERSION = "0.5.0"
'''

STUB_RUNCONFIG = '''"""Stub of module C's `sim/runconfig.py` (SPEC.md section 6.3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


class SimConfigError(ValueError):
    """Raised for an impossible or contradictory fight configuration."""


@dataclass(frozen=True)
class DowntimeWindow:
    start_s: float
    end_s: float

    def __post_init__(self) -> None:
        if self.start_s < 0:
            raise SimConfigError("downtime start must be >= 0")
        if self.end_s <= self.start_s:
            raise SimConfigError("downtime end must be after its start")


@dataclass(frozen=True)
class FightConfig:
    seconds: float = 510.0
    seed: int = 1
    ping_ms: float = 0.0
    pulse_ms: int = 30
    engine_config: Mapping[str, Any] = field(default_factory=dict)
    downtime: tuple = ()
    enemies: int = 1
    stat_overrides: Mapping[str, float] = field(default_factory=dict)
    job_overrides: Mapping[str, Any] = field(default_factory=dict)
    use_potion: bool = False
    deterministic_damage: bool = False
    tick_offset_s: float | None = None
    fast_skip_locked: bool = True
    trace: bool = False
    repo_root: Path | None = None

    def validate(self) -> None:
        if self.seconds <= 0:
            raise SimConfigError("seconds must be > 0")
        if self.pulse_ms <= 0 or self.pulse_ms > 1000:
            raise SimConfigError("pulse_ms must be in (0, 1000]")
        if self.ping_ms < 0:
            raise SimConfigError("ping_ms must be >= 0")
        if self.enemies < 1:
            raise SimConfigError("enemies must be >= 1")
        windows = sorted(self.downtime, key=lambda w: w.start_s)
        for index, window in enumerate(windows):
            if window.end_s > self.seconds:
                raise SimConfigError("downtime window ends after the fight")
            if index and window.start_s < windows[index - 1].end_s:
                raise SimConfigError("downtime windows overlap")

    def engine_overrides(self) -> dict:
        forced = {"enabled": True, "debug": False, "pulseMs": self.pulse_ms,
                  "usePotion": self.use_potion, "requireCombat": True, "requireLOS": False}
        merged = dict(forced)
        for key, value in dict(self.engine_config).items():
            if key in ("enabled", "debug"):
                continue
            merged[key] = value
        return merged
'''

STUB_CLIENT = '''"""Stub of module B's `sim/client.py` (only what module D references)."""

from __future__ import annotations

from dataclasses import dataclass


class LuaBridgeError(RuntimeError):
    """Raised when the Lua files cannot be loaded or the engine raises out of Step."""


@dataclass(frozen=True)
class ClientRejection:
    action_id: int
    target_id: int
    reason: str
    request_ms: int
'''

STUB_TABLES = '''"""Stub of module A's `sim/tables.py` (only what module D references)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class SimDataError(ValueError):
    """Raised when a data file is missing, malformed, or inconsistent with the Lua."""


@dataclass(frozen=True)
class Tables:
    stats: Mapping[str, Any]

    @classmethod
    def load(cls, data_dir: Path | None = None) -> "Tables":
        directory = Path(data_dir) if data_dir else Path(__file__).resolve().parent / "data"
        path = directory / "stats.json"
        if not path.exists():
            raise SimDataError(f"missing {path}")
        return cls(stats=json.loads(path.read_text(encoding="utf-8")))
'''

STUB_CORE = '''"""Stub of module C: deterministic, cheap, the same shapes as SPEC 6.9."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from .client import ClientRejection
from .runconfig import FightConfig, SimConfigError


class SimulationError(RuntimeError):
    """Raised when the fight cannot be completed."""


@dataclass(frozen=True)
class CastRecord:
    t_s: float
    action_id: int
    key: str
    name: str
    is_gcd: bool
    target_id: int
    potency: int
    decision: str


@dataclass(frozen=True)
class DamageRecord:
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
class CoreRejection:
    t_s: float
    action_id: int
    reason: str
    decision: str


@dataclass(frozen=True)
class FightResult:
    config: FightConfig
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
    casts: tuple = ()
    damage: tuple = ()
    rejections: tuple = ()
    client_rejections: tuple = ()
    warnings: tuple = ()
    engine_state: dict = field(default_factory=dict)

    def to_dict(self, *, include_events: bool = False) -> dict:
        def r(value):
            return round(float(value), 6)

        payload: dict[str, Any] = {
            "config": {"seconds": r(self.config.seconds), "seed": self.config.seed,
                       "ping_ms": r(self.config.ping_ms), "pulse_ms": self.config.pulse_ms,
                       "enemies": self.config.enemies},
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
            "dot_uptime": {k: r(v) for k, v in self.dot_uptime.items()},
            "song_seconds": {k: r(v) for k, v in self.song_seconds.items()},
            "song_casts": dict(self.song_casts),
            "wasted": dict(self.wasted),
            "rejections": [vars(item) for item in self.rejections],
            "client_rejections": [vars(item) for item in self.client_rejections],
            "warnings": list(self.warnings),
            "engine_state": dict(self.engine_state),
        }
        if include_events:
            payload["casts"] = [vars(item) for item in self.casts]
            payload["damage"] = [vars(item) for item in self.damage]
        return payload


_MIX = {"BurstShot": 0.34, "RefulgentArrow": 0.24, "HeartbreakShot": 0.28,
        "EmpyrealArrow": 0.17, "ApexArrow": 0.04, "IronJaws": 0.06,
        "Stormbite": 0.02, "CausticBite": 0.02, "PitchPerfect": 0.12,
        "Sidewinder": 0.04, "BlastArrow": 0.04}


def _warnings_for(config: FightConfig) -> tuple:
    overrides = dict(config.engine_config)
    out = []
    if overrides.get("advancedEnabled"):
        dots_off = (overrides.get("abilities.Stormbite") is False
                    and overrides.get("abilities.CausticBite") is False)
        if dots_off and overrides.get("multiDot"):
            out.append("Multi-dot is On but both DoTs are Off; "
                       "no secondary DoTs will be applied.")
        if dots_off:
            out.append("Iron Jaws requires both DoTs; "
                       "it will be skipped until both are active.")
    return tuple(out)


def run_fight(config: FightConfig, tables: Any = None) -> "FightResult":
    """Deterministic stand-in for a real fight; shape-compatible with module C."""
    config.validate()
    rng = random.Random(
        f"{config.seed}|{config.seconds}|{config.pulse_ms}|{config.ping_ms}|{config.enemies}")
    downtime = sum(window.end_s - window.start_s for window in config.downtime)
    active = max(config.seconds - downtime, 1.0)
    recast = 2.47 + config.ping_ms / 10000.0
    gcds = int(active / recast)
    ogcds = int(gcds * (1.40 if config.ping_ms < 100 else 1.05))
    potency = int(gcds * 268 + ogcds * 205)
    jitter = 1.0 if config.deterministic_damage else 1.0 + rng.uniform(-0.01, 0.01)
    damage = potency * 100.0 * jitter
    counts = {"WanderersMinuet": 4, "MagesBallad": 4, "ArmysPaeon": 3,
              "RagingStrikes": 5, "BattleVoice": 5, "RadiantFinale": 5,
              "RadiantEncore": 5, "Barrage": 5}
    counts = {key: max(1, int(value * config.seconds / 510.0)) for key, value in counts.items()}
    for key, share in _MIX.items():
        counts[key] = max(1, int(round(gcds * share)))
    casts = tuple(
        CastRecord(t_s=round(index * recast, 3), action_id=16495 + index % 3,
                   key=sorted(counts)[index % len(counts)], name="stub", is_gcd=True,
                   target_id=200, potency=220, decision="stub-decision")
        for index in range(min(gcds, 8)))
    damage_records = tuple(
        DamageRecord(t_s=cast.t_s, action_id=cast.action_id, key=cast.key, source="direct",
                     potency=cast.potency, amount=float(cast.potency * 100),
                     crit=False, direct_hit=False, multiplier=1.0)
        for cast in casts)
    return FightResult(
        config=config,
        duration_s=float(config.seconds),
        total_damage=damage,
        dps=damage / float(config.seconds),
        total_potency=potency,
        potency_per_second=potency / float(config.seconds),
        gcd_count=gcds,
        ogcd_count=ogcds,
        gcd_uptime=min(0.995, active / config.seconds * 0.995),
        clipped_s=round(0.4 + rng.random() * 0.1, 3),
        action_counts=dict(sorted(counts.items())),
        damage_by_action={key: float(value * 1000) for key, value in sorted(counts.items())},
        dot_uptime={"Stormbite": 0.991, "CausticBite": 0.988},
        song_seconds={"WM": 43.9, "MB": 42.4, "AP": 35.0},
        song_casts={"WM": 4, "MB": 4, "AP": 3},
        wasted={"repertoire_overcap": 2, "soul_voice_overcap": 0,
                "hawks_eye_overwritten": 3, "charge_overcap": 1},
        casts=casts,
        damage=damage_records,
        rejections=(),
        client_rejections=(),
        warnings=_warnings_for(config),
        engine_state={"lastDecision": "stub-decision"},
    )


class Simulation:
    """Minimal stand-in so `Simulation(config).run()` exists."""

    def __init__(self, config: FightConfig, tables: Any = None) -> None:
        self.config = config
        self.tables = tables

    def run(self) -> "FightResult":
        return run_fight(self.config, self.tables)
'''

STUB_STATS = '{\n  "potency_to_damage": 100.0\n}\n'


def _build_stub_root() -> Path:
    """Create a throwaway `sim` package: module D's real files plus upstream stubs."""
    root = Path(tempfile.mkdtemp(prefix="cielbard-sim-stub-"))
    atexit.register(shutil.rmtree, root, True)
    package = root / "sim"
    (package / "data").mkdir(parents=True)
    (package / "__init__.py").write_text(STUB_INIT, encoding="utf-8", newline="\n")
    (package / "runconfig.py").write_text(STUB_RUNCONFIG, encoding="utf-8", newline="\n")
    (package / "client.py").write_text(STUB_CLIENT, encoding="utf-8", newline="\n")
    (package / "tables.py").write_text(STUB_TABLES, encoding="utf-8", newline="\n")
    (package / "core.py").write_text(STUB_CORE, encoding="utf-8", newline="\n")
    (package / "data" / "stats.json").write_text(STUB_STATS, encoding="utf-8", newline="\n")
    for name in OWNED_FILES:
        shutil.copyfile(REPO_ROOT / "sim" / name, package / name)
    return root


def _resolve_sim_root() -> tuple[Path, bool]:
    """Return `(import root, using_stub)`: the repo once module C landed, else a stub."""
    if (REPO_ROOT / "sim" / "core.py").exists() and (REPO_ROOT / "sim" / "__init__.py").exists():
        return REPO_ROOT, False
    return _build_stub_root(), True


SIM_ROOT, USING_STUB = _resolve_sim_root()

if USING_STUB:
    for _name in [name for name in list(sys.modules)
                  if name == "sim" or name.startswith("sim.")]:
        del sys.modules[_name]
if str(SIM_ROOT) not in sys.path:
    sys.path.insert(0, str(SIM_ROOT))

from sim import batch as sim_batch  # noqa: E402
from sim import calibrate as sim_calibrate  # noqa: E402
from sim import report as sim_report  # noqa: E402
from sim import run as sim_run  # noqa: E402
from sim import sweep as sim_sweep  # noqa: E402
from sim.runconfig import FightConfig, SimConfigError  # noqa: E402

CSV_HEADER = ("rank,name,amount,aDPS,rDPS,nDPS,duration_s,report_code,fight_id,"
              "bard_actor_id,final_raging_s,final_battle_voice_s,final_radiant_finale_s,"
              "final_party_anchor_s,death_after_final_anchor_s,rough_cycle_phase_s")
CSV_ROWS = (
    "1,Alpha,1.0,35131.9,41540.6,32151.5,509.9,abc,1,1,486.9,489.1,489.8,489.1,20.8,29.9",
    "2,Beta,1.0,34915.7,40105.9,32325.7,512.7,def,2,2,486.2,490.5,491.2,490.5,22.1,32.7",
    "3,Gamma,1.0,33858.8,40928.2,32648.9,532.0,ghi,3,3,494.1,492.8,493.5,492.8,61.2,52.0",
)


def _env() -> dict:
    """Environment for a CLI subprocess: the chosen sim root first on the path."""
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(SIM_ROOT) + (os.pathsep + existing if existing else "")
    return env


def run_cli(module: str, *args: str) -> subprocess.CompletedProcess:
    """Invoke `python -m <module> <args>` against the resolved sim root."""
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        cwd=str(SIM_ROOT), env=_env(), capture_output=True, text=True, timeout=600)


def write_csv(path: Path, rows=CSV_ROWS, header: str = CSV_HEADER) -> Path:
    """Write a killtime.csv fixture."""
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8", newline="\n")
    return path


def fake_result() -> SimpleNamespace:
    """A FightResult-shaped object carrying the exact numbers of the SPEC 7.1 sample."""
    config = SimpleNamespace(seconds=510.0, seed=1, ping_ms=0.0, pulse_ms=30, enemies=1)
    return SimpleNamespace(
        config=config, duration_s=510.0, total_damage=17662830.0, dps=34633.0,
        total_potency=104215, potency_per_second=204.3, gcd_count=205, ogcd_count=288,
        gcd_uptime=0.987, clipped_s=0.42,
        action_counts={"ApexArrow": 8, "Barrage": 4, "BattleVoice": 5, "BurstShot": 63},
        damage_by_action={}, dot_uptime={"Stormbite": 0.991, "CausticBite": 0.988},
        song_seconds={"WM": 175.6, "MB": 169.6, "AP": 105.0},
        song_casts={"WM": 4, "MB": 4, "AP": 3},
        wasted={"repertoire_overcap": 2, "soul_voice_overcap": 0, "charge_overcap": 1},
        casts=(), damage=(), rejections=(), client_rejections=(), warnings=(),
        engine_state={})


def fake_summary(dps: float, seconds: float) -> "sim_batch.BatchSummary":
    """A BatchSummary with plausible fields, for tests that must not run fights."""
    return sim_batch.BatchSummary(
        n=5, seconds=seconds, dps_mean=dps, dps_stdev=dps * 0.01,
        dps_p05=dps * 0.98, dps_p50=dps, dps_p95=dps * 1.02,
        gcd_mean=seconds / 2.47,
        action_counts_mean={"BurstShot": 63.0, "EmpyrealArrow": 34.0, "ApexArrow": 8.4},
        dot_uptime_mean={"Stormbite": 0.99, "CausticBite": 0.98},
        rejections_total=0)


class ReportFormattingTests(unittest.TestCase):
    """`sim.report` is pure formatting and is tested without running a fight."""

    def test_header_line_shape(self) -> None:
        header = sim_report.header_line()
        assert header.startswith("CielBard sim "), header
        assert " | engine " in header, header

    def test_labels_sit_in_the_eight_char_column(self) -> None:
        line = sim_report.labelled("fight", "510.0s")
        assert line == "fight    510.0s", repr(line)

    def test_format_counts_wraps_and_indents(self) -> None:
        counts = {f"Action{index:02d}": index for index in range(1, 21)}
        block = sim_report.format_counts(counts, width=60, indent=9)
        lines = block.split("\n")
        assert len(lines) > 1, block
        for line in lines[1:]:
            assert line.startswith(" " * 9), repr(line)
            assert len(line) <= 60, repr(line)
        assert block.index("Action01") < block.index("Action20"), block

    def test_format_counts_empty_is_none(self) -> None:
        assert sim_report.format_counts({}) == "none"

    def test_format_table_alignment_row(self) -> None:
        table = sim_report.format_table(["a", "b"], [[1, 2]], "lr")
        lines = table.split("\n")
        assert lines[1] == "|---|---:|", lines[1]
        assert lines[2] == "| 1 | 2 |", lines[2]

    def test_format_fight_matches_the_documented_layout(self) -> None:
        text = sim_report.format_fight(fake_result())
        lines = text.splitlines()
        assert lines[1] == ("fight    510.0s  seed=1  ping=0ms  pulse=30ms  gcd=2.46s  "
                            "enemies=1"), repr(lines[1])
        assert lines[2] == ("damage   17662830   dps 34633.0   potency 104215 "
                            "(204.3/s)"), repr(lines[2])
        assert lines[3] == "gcds     205 (24.12/min)   ogcds 288   weaves/gcd 1.40", lines[3]
        assert lines[4] == "uptime   gcd 98.7%   clipped 0.42s   rejections 0", lines[4]
        assert lines[5] == "dots     Stormbite 99.1%   CausticBite 98.8%", lines[5]
        assert lines[6] == "songs    WM 4x 43.9s   MB 4x 42.4s   AP 3x 35.0s", lines[6]
        assert lines[7] == "waste    repertoire 2   soulvoice 0   charges 1", lines[7]
        assert lines[8].startswith("counts   ApexArrow 8  Barrage 4  "), lines[8]

    def test_song_line_is_seconds_per_cast(self) -> None:
        result = fake_result()
        line = sim_report.format_fight(result).splitlines()[6]
        assert "WM 4x 43.9s" in line, line
        assert result.song_seconds["WM"] == 175.6, "the totals themselves are untouched"

    def test_format_seeds_compresses_runs(self) -> None:
        assert sim_report.format_seeds([1, 2, 3, 4, 5]) == "1-5"
        assert sim_report.format_seeds([1, 5, 9]) == "1,5,9"
        assert sim_report.format_seeds([3, 1, 2, 7]) == "1-3,7"


class RunCliTests(unittest.TestCase):
    """SPEC.md section 7.6 items 1-6."""

    LABELS = ("fight", "damage", "gcds", "uptime", "dots", "songs", "waste", "counts")

    @classmethod
    def setUpClass(cls) -> None:
        cls.proc = run_cli("sim.run", "--seconds", "60", "--seed", "1", "--ping", "0")

    def test_run_smoke_60s(self) -> None:
        assert self.proc.returncode == 0, self.proc.stderr
        first = self.proc.stdout.splitlines()[0]
        import re
        assert re.match(r"^CielBard sim \d+\.\d+\.\d+ \| engine 0\.5\.1$", first), first

    def test_run_output_layout(self) -> None:
        lines = self.proc.stdout.splitlines()
        assert len(lines) >= 1 + len(self.LABELS), self.proc.stdout
        for index, label in enumerate(self.LABELS, start=1):
            line = lines[index]
            assert line.startswith(f"{label:<8} "), repr(line)
            assert line == line.rstrip(), repr(line)
        assert "\r" not in self.proc.stdout, "line endings must be LF"

    def test_run_deterministic(self) -> None:
        again = run_cli("sim.run", "--seconds", "60", "--seed", "1", "--ping", "0")
        assert again.returncode == 0, again.stderr
        assert again.stdout == self.proc.stdout, (
            "two identical invocations disagreed (SPEC.md 0.1 rule 4). Known upstream "
            "cause: lupa 2.8 embeds Lua 5.5, whose per-state string hash seed is derived "
            "from the wall clock, so `pairs()` order over string keys changes about once "
            "a second and leaks into the engine's decisions. Fix belongs in sim/client.py "
            "or sim/core.py, not here.\n"
            f"--- first ---\n{self.proc.stdout}\n--- second ---\n{again.stdout}")

    def test_run_json_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "fight.json"
            proc = run_cli("sim.run", "--seconds", "60", "--seed", "2", "--quiet",
                           "--json", str(target))
            assert proc.returncode == 0, proc.stderr
            assert proc.stdout == "", proc.stdout
            payload = json.loads(target.read_text(encoding="utf-8"))
        for key in ("duration_s", "total_damage", "dps", "total_potency", "gcd_count",
                    "ogcd_count", "action_counts", "dot_uptime", "casts"):
            assert key in payload, sorted(payload)
        assert payload["duration_s"] == 60.0, payload["duration_s"]

    def test_trace_prints_one_line_per_cast(self) -> None:
        proc = run_cli("sim.run", "--seconds", "60", "--seed", "1", "--trace")
        assert proc.returncode == 0, proc.stderr
        traced = [line for line in proc.stdout.splitlines() if line.startswith("trace   ")]
        assert traced, proc.stdout

    def test_bad_flag_exits_2(self) -> None:
        proc = run_cli("sim.run", "--definitely-not-a-flag")
        assert proc.returncode == 2, (proc.returncode, proc.stderr)

    def test_bad_set_value_exits_2(self) -> None:
        proc = run_cli("sim.run", "--seconds", "60", "--set", "noEqualsSign")
        assert proc.returncode == 2, (proc.returncode, proc.stderr)
        assert proc.stderr.startswith("sim.run: "), proc.stderr

    def test_downtime_overlap_exits_2(self) -> None:
        proc = run_cli("sim.run", "--seconds", "60", "--downtime", "5:20",
                       "--downtime", "10:25")
        assert proc.returncode == 2, (proc.returncode, proc.stderr)
        assert "sim.run:" in proc.stderr, proc.stderr

    def test_nonpositive_seconds_exits_2(self) -> None:
        proc = run_cli("sim.run", "--seconds", "0")
        assert proc.returncode == 2, (proc.returncode, proc.stderr)

    def test_strict_exit_4_on_warning(self) -> None:
        proc = run_cli("sim.run", "--seconds", "60", "--quiet", "--strict",
                       "--set", "advancedEnabled=true",
                       "--set", "abilities.Stormbite=false",
                       "--set", "abilities.CausticBite=false",
                       "--set", "multiDot=true")
        assert proc.returncode == 4, (proc.returncode, proc.stdout, proc.stderr)
        assert "strict:" in proc.stderr, proc.stderr

    def test_strict_exit_0_on_clean_run(self) -> None:
        proc = run_cli("sim.run", "--seconds", "60", "--quiet", "--strict")
        assert proc.returncode == 0, (proc.returncode, proc.stderr)


class ParsingTests(unittest.TestCase):
    """Flag parsing helpers shared by every module D entry point."""

    def test_parse_value_types(self) -> None:
        assert sim_run.parse_value("true") is True
        assert sim_run.parse_value("false") is False
        assert sim_run.parse_value("12") == 12
        assert sim_run.parse_value("2.5") == 2.5
        assert sim_run.parse_value("FULL") == "FULL"

    def test_parse_assignment_requires_equals(self) -> None:
        try:
            sim_run.parse_assignment("nope")
        except SimConfigError:
            pass
        else:  # pragma: no cover - the call must raise
            raise AssertionError("expected SimConfigError")

    def test_parse_downtime(self) -> None:
        window = sim_run.parse_downtime("10:25.5")
        assert (window.start_s, window.end_s) == (10.0, 25.5)

    def test_parse_seeds_forms(self) -> None:
        assert sim_batch.parse_seeds("1-5") == [1, 2, 3, 4, 5]
        assert sim_batch.parse_seeds("1,5,9") == [1, 5, 9]
        assert sim_batch.parse_seeds("1-3,9") == [1, 2, 3, 9]

    def test_parse_seeds_rejects_garbage(self) -> None:
        for text in ("", "abc", "5-1"):
            try:
                sim_batch.parse_seeds(text)
            except SimConfigError:
                continue
            raise AssertionError(f"expected SimConfigError for {text!r}")


class BatchTests(unittest.TestCase):
    """SPEC.md section 7.6 items 7-8."""

    def test_batch_summary_stats(self) -> None:
        base = FightConfig(seconds=60.0, seed=1)
        summary, results = sim_batch.run_batch(base, seeds=[1, 2, 3, 4, 5], workers=1)
        assert summary.n == 5, summary.n
        assert len(results) == 5
        assert summary.dps_p05 <= summary.dps_p50 <= summary.dps_p95, summary
        assert summary.seconds == 60.0
        assert summary.gcd_mean > 0
        assert summary.action_counts_mean, summary.action_counts_mean
        assert list(summary.action_counts_mean) == sorted(summary.action_counts_mean)

    def test_summary_to_dict_is_json_stable(self) -> None:
        summary = fake_summary(34633.0, 510.0)
        text = json.dumps(summary.to_dict(), sort_keys=True)
        assert json.dumps(summary.to_dict(), sort_keys=True) == text

    def test_percentile_interpolates(self) -> None:
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert sim_batch.percentile(values, 0.5) == 3.0
        assert sim_batch.percentile(values, 0.0) == 1.0
        assert sim_batch.percentile(values, 1.0) == 5.0
        assert sim_batch.percentile([], 0.5) == 0.0

    def test_format_batch_layout(self) -> None:
        text = sim_report.format_batch(fake_summary(34633.0, 510.0))
        lines = text.splitlines()
        for index, label in enumerate(("batch", "dps", "gcds", "dots", "counts"), start=1):
            assert lines[index].startswith(f"{label:<8} "), repr(lines[index])

    @unittest.skipIf(FAST, "CIELBARD_SIM_FAST=1 skips the multi-process batch")
    def test_batch_worker_equivalence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            one = Path(tmp) / "w1.json"
            two = Path(tmp) / "w2.json"
            first = run_cli("sim.batch", "--seconds", "60", "--seeds", "1-3",
                            "--workers", "1", "--quiet", "--json", str(one))
            second = run_cli("sim.batch", "--seconds", "60", "--seeds", "1-3",
                             "--workers", "2", "--quiet", "--json", str(two))
            assert first.returncode == 0, first.stderr
            assert second.returncode == 0, second.stderr
            assert json.loads(one.read_text(encoding="utf-8")) == \
                json.loads(two.read_text(encoding="utf-8")), (
                    "workers=1 and workers=2 disagreed. The aggregation is order-free, so "
                    "a difference here is the same wall-clock-seeded Lua `pairs()` order "
                    "problem described in test_run_deterministic.")

    def test_batch_cli_prints_summary(self) -> None:
        proc = run_cli("sim.batch", "--seconds", "60", "--seeds", "1,2", "--workers", "1")
        assert proc.returncode == 0, proc.stderr
        lines = proc.stdout.splitlines()
        assert lines[1].startswith("batch   "), lines


class SweepTests(unittest.TestCase):
    """SPEC.md section 7.6 item 9."""

    def test_expand_points_order(self) -> None:
        points = sim_sweep.expand_points({"maxWeaves": [1, 2], "apexBurstGauge": [80, 90]})
        assert points == [
            {"apexBurstGauge": 80, "maxWeaves": 1},
            {"apexBurstGauge": 80, "maxWeaves": 2},
            {"apexBurstGauge": 90, "maxWeaves": 1},
            {"apexBurstGauge": 90, "maxWeaves": 2},
        ], points

    def test_empty_axis_raises(self) -> None:
        try:
            sim_sweep.expand_points({"maxWeaves": []})
        except SimConfigError:
            return
        raise AssertionError("expected SimConfigError")

    def test_apply_point_splits_reserved_names(self) -> None:
        base = FightConfig(seconds=60.0, seed=1)
        config = sim_sweep.apply_point(base, {"ping_ms": 50, "pulse_ms": 50, "maxWeaves": 1})
        assert config.ping_ms == 50.0
        assert config.pulse_ms == 50
        assert config.engine_config["maxWeaves"] == 1
        assert base.engine_config == {}

    def test_sweep_shape_and_order(self) -> None:
        base = FightConfig(seconds=60.0, seed=1)
        points = sim_sweep.sweep(base, {"maxWeaves": [1, 2], "ping_ms": [0, 50]},
                                 seeds=[1], workers=1)
        assert len(points) == 4, len(points)
        assert [point for point, _ in points] == [
            {"maxWeaves": 1, "ping_ms": 0},
            {"maxWeaves": 1, "ping_ms": 50},
            {"maxWeaves": 2, "ping_ms": 0},
            {"maxWeaves": 2, "ping_ms": 50},
        ]
        for _, summary in points:
            assert summary.n == 1

    def test_write_csv_columns(self) -> None:
        points = [({"maxWeaves": 1}, fake_summary(1000.0, 60.0)),
                  ({"maxWeaves": 2}, fake_summary(1100.0, 60.0))]
        with tempfile.TemporaryDirectory() as tmp:
            path = sim_sweep.write_csv(points, Path(tmp) / "nested" / "sweep.csv")
            text = path.read_text(encoding="utf-8")
        header, *rows = text.strip().split("\n")
        assert header.split(",")[:5] == ["maxWeaves", "n", "dps_mean", "dps_stdev",
                                         "gcd_mean"], header
        assert "count_ApexArrow" in header, header
        assert len(rows) == 2, rows
        assert "\r" not in text


class CalibrateTests(unittest.TestCase):
    """SPEC.md section 7.6 items 10-12."""

    REQUIRED_HEADINGS = (
        "## Fit by fight length",
        "## Fit by kill-window band",
        "## Per-action counts at",
        "## Per-parse residuals",
        "## Unverified assumptions",
        "## Known limitations",
    )

    def _runner(self):
        def run(seconds, seeds):
            return fake_summary(200.0 + seconds / 10.0, seconds)
        return run

    def test_calibrate_writes_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            csv_path = write_csv(tmp_path / "killtime.csv")
            out = tmp_path / "out" / "calibration.md"
            payload = sim_calibrate.calibrate(
                seeds=[1, 2, 3], csv_path=csv_path, out_path=out,
                durations=[510.0, 532.0], current_scalar=100.0,
                runner=self._runner(), min_parses=3, write_scalar=True)
            assert payload["fitted_potency_to_damage"] > 0, payload
            text = out.read_text(encoding="utf-8")
            for heading in self.REQUIRED_HEADINGS:
                assert heading in text, heading
            assert text.startswith("# CielBard sim calibration"), text[:60]
            assert "- fitted potency_to_damage:" in text
            assert "- residual: mean absolute error" in text
            written = json.loads((out.parent / "calibration.json").read_text(encoding="utf-8"))
            assert written["parse_count"] == 3, written["parse_count"]
            assert len(written["residuals"]) == 3
            assert written["unverified"], "the report must list its assumptions"
            override = json.loads(
                (out.parent / "stats.override.json").read_text(encoding="utf-8"))
            assert override["potency_to_damage"] == payload["fitted_potency_to_damage"]

    def test_fit_recovers_a_known_scalar(self) -> None:
        """A runner whose DPS is exactly actual/2 must fit a scalar of 2x the current."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            csv_path = write_csv(tmp_path / "killtime.csv", rows=(
                "1,A,1.0,1000.0,1.0,1.0,510.0,x,1,1,1,1,1,1,10.0,1.0",
                "2,B,1.0,1000.0,1.0,1.0,510.0,x,2,2,1,1,1,1,25.0,1.0",
                "3,C,1.0,1000.0,1.0,1.0,510.0,x,3,3,1,1,1,1,70.0,1.0",
            ))
            payload = sim_calibrate.calibrate(
                seeds=[1], csv_path=csv_path, out_path=tmp_path / "calibration.md",
                durations=[510.0], current_scalar=100.0, min_parses=3,
                runner=lambda seconds, seeds: fake_summary(500.0, seconds))
        assert abs(payload["fitted_potency_to_damage"] - 200.0) < 1e-6, payload
        assert abs(payload["residual_mean_abs_pct"]) < 1e-6, payload
        bands = {row["band"]: row["parses"] for row in payload["by_band"]}
        assert bands == {"<20": 1, "20-30": 1, "31-60": 0, ">60": 1}, bands

    def test_calibrate_missing_column_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_csv(Path(tmp) / "killtime.csv",
                             header=CSV_HEADER.replace(",nDPS", ""))
            try:
                sim_calibrate.load_parses(path, min_parses=3)
            except sim_calibrate.CalibrationDataError as exc:
                assert "nDPS" in str(exc), str(exc)
                return
        raise AssertionError("expected CalibrationDataError")

    def test_calibrate_short_file_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_csv(Path(tmp) / "killtime.csv")
            try:
                sim_calibrate.load_parses(path)
            except sim_calibrate.CalibrationDataError as exc:
                assert "at least 10" in str(exc), str(exc)
                return
        raise AssertionError("expected CalibrationDataError")

    def test_calibrate_missing_file_raises(self) -> None:
        try:
            sim_calibrate.load_parses(Path(tempfile.gettempdir()) / "no-such-killtime.csv")
        except sim_calibrate.CalibrationDataError:
            return
        raise AssertionError("expected CalibrationDataError")

    def test_calibrate_never_touches_data_dir(self) -> None:
        stats = SIM_ROOT / "sim" / "data" / "stats.json"
        if not stats.exists():  # pragma: no cover - module A has not landed
            raise unittest.SkipTest("sim/data/stats.json is not present yet")
        before = (stats.stat().st_mtime_ns, stats.read_bytes())
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            csv_path = write_csv(tmp_path / "killtime.csv")
            sim_calibrate.calibrate(
                seeds=[1], csv_path=csv_path, out_path=tmp_path / "calibration.md",
                durations=[510.0], current_scalar=100.0, min_parses=3,
                runner=self._runner(), write_scalar=True)
        after = (stats.stat().st_mtime_ns, stats.read_bytes())
        assert before == after, "calibration must never write inside sim/data"

    def test_calibrate_refuses_to_write_into_data_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = write_csv(Path(tmp) / "killtime.csv")
            try:
                sim_calibrate.calibrate(
                    seeds=[1], csv_path=csv_path,
                    out_path=SIM_ROOT / "sim" / "data" / "calibration.md",
                    durations=[510.0], current_scalar=100.0, min_parses=3,
                    runner=self._runner())
            except sim_calibrate.CalibrationDataError:
                return
        raise AssertionError("expected CalibrationDataError")

    def test_band_boundaries(self) -> None:
        assert sim_calibrate.band_for(19.9) == "<20"
        assert sim_calibrate.band_for(20.0) == "20-30"
        assert sim_calibrate.band_for(30.0) == "20-30"
        assert sim_calibrate.band_for(30.1) == "31-60"
        assert sim_calibrate.band_for(60.0) == "31-60"
        assert sim_calibrate.band_for(60.1) == ">60"

    def test_nearest_duration_matching(self) -> None:
        options = [502.0, 510.0, 520.0, 532.0, 550.0]
        assert sim_calibrate.nearest(509.9, options) == 510.0
        assert sim_calibrate.nearest(600.0, options) == 550.0
        assert sim_calibrate.nearest(506.0, options) == 502.0

    def test_real_killtime_csv_loads(self) -> None:
        path = REPO_ROOT / "bard-analysis" / "output" / "killtime" / "killtime.csv"
        if not path.exists():  # pragma: no cover - the analysis output is optional
            raise unittest.SkipTest("killtime.csv is not present")
        parses = sim_calibrate.load_parses(path)
        assert len(parses) >= 10, len(parses)
        assert all(parse.duration_s > 0 for parse in parses)


if __name__ == "__main__":  # pragma: no cover - direct invocation
    unittest.main()
