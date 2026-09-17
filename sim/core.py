"""Discrete-event game core of the CielBard simulator.

:class:`Simulation` owns the clock (integer microseconds), the event heap and
every piece of game state.  Each pulse it mirrors that state into
:class:`~sim.client.FakeClient`, lets the shipped Lua engine take exactly one
decision, and resolves at most one cast request.  Nothing else in the simulator
advances time.

Every mechanic number comes from the tables in ``sim/data``; the only literals
here are ability keys, event kinds and simulator policy limits.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from sim.client import (
    ActionSpec,
    ActionView,
    BuffView,
    CastRequest,
    ClientRejection,
    EntityView,
    FakeClient,
    PlayerView,
    PotionView,
)
from sim.damage import BuffSnapshot, DamageModel, StatProfile
from sim.events import (
    ACTION_EXECUTE,
    AUTO_ATTACK,
    COOLDOWN_READY,
    DOWNTIME_END,
    DOWNTIME_START,
    FIGHT_END,
    GCD_READY,
    LOCK_END,
    SERVER_TICK,
    STATUS_EXPIRE,
    Event,
    EventQueue,
)
from sim.rng import SeededRNG
from sim.runconfig import FightConfig, SimConfigError
from sim.tables import (
    ActionData,
    SimDataError,
    Tables,
    apex_potency,
    gcd_recast,
    _validate_job,  # job_overrides get the same checks as job.json (SPEC 4.4)
)

__all__ = [
    "SimulationError",
    "StatusInstance",
    "CastRecord",
    "DamageRecord",
    "CoreRejection",
    "FightResult",
    "Simulation",
    "run_fight",
]

# --- simulator policy (not game mechanics) ---------------------------------
MAX_REQUESTS_PER_PULSE = 4
MAX_REJECTION_FRACTION = 0.05
US = 1_000_000
# "Undamaged" on the client's 0..100 HP scale; a unit of the API, not a game mechanic.
FULL_HP_PERCENT = 100.0

# Ability keys the engine falls back to below level 100; never castable here.
LEVEL_SYNC_DISABLED = frozenset(
    {"HeavyShot", "Windbite", "VenomousBite", "QuickNock", "Bloodletter"}
)

# Short song codes.  These are labels, not mechanics: the status key of a song
# is the same string as its ability key, and the gauge reports the index below.
SONG_CODES: Dict[str, str] = {
    "WanderersMinuet": "WM",
    "MagesBallad": "MB",
    "ArmysPaeon": "AP",
}
SONG_KEYS: Dict[str, str] = {code: key for key, code in SONG_CODES.items()}
SONG_ORDER: Tuple[str, ...] = ("WM", "MB", "AP")

PLAYER = 0

KEY_APEX = "ApexArrow"
KEY_BLAST_READY = "BlastArrowReady"
KEY_EMPYREAL = "EmpyrealArrow"
KEY_ENCORE = "RadiantEncore"
KEY_ENCORE_READY = "RadiantEncoreReady"
KEY_FINALE = "RadiantFinale"
KEY_HAWKS_EYE = "HawksEye"
KEY_IRON_JAWS = "IronJaws"
KEY_MEDICATED = "Medicated"
KEY_MUSE = "ArmysMuse"
KEY_ETHOS = "ArmysEthos"
KEY_PITCH_PERFECT = "PitchPerfect"
KEY_POTION = "Potion"

LEGACY_JOB_KEYS = frozenset({"repertoire_requires_dot"})
"""Superseded `job.json` keys a `job_overrides` mapping may still set.

`repertoire_requires_dot` is the pre-MECHANICS_CORRECTIONS spelling of
`repertoire_independent_of_dots` and is read as its inverse when the new key is
absent (SPEC 4.4)."""

CORE_ONLY_JOB_KEYS = frozenset({"damage_delay_s", "level_sync_disabled", "potion_hqid"})
"""Job knobs the core reads with an in-code default instead of from `job.json`.

They are not in the data file, so `_apply_job_overrides` has to allow them by name;
everything else a `job_overrides` mapping names must exist in `job.json`."""

# Mirrors CielBardData.Potions[1] (Grade 4 Gemdraught of Dexterity) plus
# CielBardData.HQOffset.  Overridable through FightConfig.job_overrides.
DEFAULT_POTION_HQID = 1049235


class SimulationError(RuntimeError):
    """Raised when the fight cannot be completed (Lua error, client callback error)."""


@dataclass
class StatusInstance:
    """One active buff or debuff, on the player or on an entity."""

    key: str
    expires_us: int
    stacks: int = 1
    snapshot: Optional[BuffSnapshot] = None
    mult_override: Optional[float] = None
    codas: int = 0


@dataclass(frozen=True)
class CastRecord:
    """One accepted action request."""

    t_s: float
    action_id: int
    key: str                 # "" for unmapped ids
    name: str
    is_gcd: bool
    target_id: int
    potency: int
    decision: str            # CielBardEngine.state.lastDecision at the pulse


@dataclass(frozen=True)
class DamageRecord:
    """One damage instance: a direct hit, a DoT tick or an auto attack."""

    t_s: float
    action_id: int
    key: str
    source: str              # "direct" | "dot" | "auto"
    potency: int
    amount: float
    crit: bool
    direct_hit: bool
    multiplier: float


@dataclass(frozen=True)
class CoreRejection:
    """A request the core refused after the client accepted it."""

    t_s: float
    action_id: int
    reason: str              # locked | gcd-not-ready | unavailable | unknown-action |
                             # multiple-requests-per-pulse
    decision: str


def _r6(value: float) -> float:
    """Round to six decimals so serialised floats are byte-stable."""
    return round(float(value), 6)


@dataclass(frozen=True)
class FightResult:
    """Everything one fight produced, ready for reporting or aggregation."""

    config: FightConfig
    duration_s: float
    total_damage: float
    dps: float
    total_potency: int
    potency_per_second: float
    gcd_count: int
    ogcd_count: int
    gcd_uptime: float             # fraction of `duration_s` the GCD was rolling
    clipped_s: float              # sum of (gcd gap - recast) over all GCD pairs
    action_counts: Dict[str, int]  # by ability key, sorted by key
    damage_by_action: Dict[str, float]
    dot_uptime: Dict[str, float]  # key -> fraction of the fight the DoT was on the target
    song_seconds: Dict[str, float]
    song_casts: Dict[str, int]
    wasted: Dict[str, int]        # "repertoire_overcap", "soul_voice_overcap",
                                  # "hawks_eye_overwritten", "charge_overcap"
    casts: Tuple[CastRecord, ...]
    damage: Tuple[DamageRecord, ...]
    rejections: Tuple[CoreRejection, ...]
    client_rejections: Tuple[ClientRejection, ...]
    warnings: Tuple[str, ...]     # engine configuration warnings
    engine_state: Dict[str, Any]  # final CielBardEngine.state snapshot
    # Realized rates over every damage instance, so the stat model's inputs can be
    # checked against the parses they came from instead of being invisible.
    crit_rate: float = 0.0
    dh_rate: float = 0.0
    damage_event_count: int = 0

    def to_dict(self, *, include_events: bool = False) -> dict:
        """JSON-ready. `include_events=False` (default) drops `casts` and `damage` so a
        batch of 1000 fights stays small. Floats are rounded to 6 decimals so the JSON
        is byte-stable."""
        out: Dict[str, Any] = {
            "config": self.config.to_dict(),
            "duration_s": _r6(self.duration_s),
            "total_damage": _r6(self.total_damage),
            "dps": _r6(self.dps),
            "total_potency": int(self.total_potency),
            "potency_per_second": _r6(self.potency_per_second),
            "gcd_count": int(self.gcd_count),
            "ogcd_count": int(self.ogcd_count),
            "gcd_uptime": _r6(self.gcd_uptime),
            "clipped_s": _r6(self.clipped_s),
            "crit_rate": _r6(self.crit_rate),
            "dh_rate": _r6(self.dh_rate),
            "damage_event_count": int(self.damage_event_count),
            "action_counts": {k: int(self.action_counts[k]) for k in sorted(self.action_counts)},
            "damage_by_action": {
                k: _r6(self.damage_by_action[k]) for k in sorted(self.damage_by_action)
            },
            "dot_uptime": {k: _r6(self.dot_uptime[k]) for k in sorted(self.dot_uptime)},
            "song_seconds": {k: _r6(self.song_seconds[k]) for k in sorted(self.song_seconds)},
            "song_casts": {k: int(self.song_casts[k]) for k in sorted(self.song_casts)},
            "wasted": {k: int(self.wasted[k]) for k in sorted(self.wasted)},
            "rejections": [
                {
                    "t_s": _r6(r.t_s),
                    "action_id": int(r.action_id),
                    "reason": r.reason,
                    "decision": r.decision,
                }
                for r in self.rejections
            ],
            "client_rejections": [
                {
                    "action_id": int(r.action_id),
                    "target_id": int(r.target_id),
                    "reason": r.reason,
                    "request_ms": int(r.request_ms),
                }
                for r in self.client_rejections
            ],
            "warnings": list(self.warnings),
            "engine_state": {k: self.engine_state[k] for k in sorted(self.engine_state)},
        }
        if include_events:
            out["casts"] = [
                {
                    "t_s": _r6(c.t_s),
                    "action_id": int(c.action_id),
                    "key": c.key,
                    "name": c.name,
                    "is_gcd": bool(c.is_gcd),
                    "target_id": int(c.target_id),
                    "potency": int(c.potency),
                    "decision": c.decision,
                }
                for c in self.casts
            ]
            out["damage"] = [
                {
                    "t_s": _r6(d.t_s),
                    "action_id": int(d.action_id),
                    "key": d.key,
                    "source": d.source,
                    "potency": int(d.potency),
                    "amount": _r6(d.amount),
                    "crit": bool(d.crit),
                    "direct_hit": bool(d.direct_hit),
                    "multiplier": _r6(d.multiplier),
                }
                for d in self.damage
            ]
        return out


class Simulation:
    """One fight: owns the clock, the event queue, the game state and the Lua client."""

    def __init__(self, config: FightConfig, tables: Optional[Tables] = None) -> None:
        """`tables` may be shared across fights (it is read-only)."""
        config.validate()
        self.config = config
        self.tables = tables if tables is not None else Tables.load()

        self.job: Dict[str, Any] = dict(self.tables.job)
        self._apply_job_overrides(dict(config.job_overrides))
        self.stats: Dict[str, Any] = dict(self.tables.stats)
        self.stats.update({k: v for k, v in config.stat_overrides.items()})

        self.rng = SeededRNG(config.seed)
        # Every key of stats.json is overridable, but only some of them are
        # `StatProfile` fields: `potion_damage_mult` and `auto_attack_dps` are read
        # by the core instead. Validate against the table (the typo protection the
        # spec asks for) and hand `StatProfile` only the fields it owns.
        unknown = sorted(set(config.stat_overrides) - set(self.tables.stats))
        if unknown:
            raise SimConfigError(
                "unknown --stat key(s): " + ", ".join(unknown)
                + "; stats.json defines " + ", ".join(sorted(self.tables.stats))
            )
        stat_overrides: Dict[str, float] = {
            k: float(v) for k, v in config.stat_overrides.items()
            if k in StatProfile.__dataclass_fields__
        }
        if config.deterministic_damage:
            # `--deterministic` is the expected-value mode: no crit, direct-hit or
            # variance draw at all. `damage_variance = 0` keeps its narrower meaning.
            stat_overrides["damage_variance"] = 0.0
            stat_overrides["expected_value"] = True
        self.profile = StatProfile.from_tables(self.tables, **stat_overrides)
        self.damage_model = DamageModel(self.profile, self.rng)

        # --- clock and scheduling ---------------------------------------
        self._us: int = 0
        self.pulse_us: int = int(config.pulse_ms) * 1000
        self.end_us: int = int(round(float(config.seconds) * US))
        self.queue = EventQueue()

        # --- ids ---------------------------------------------------------
        self.player_id: int = 100
        self.target_id: int = 200
        self._clone_base_id: int = 300

        # --- job knobs ---------------------------------------------------
        self._gcd_base_s = float(self.job["gcd_base_s"])
        self._gcd_rounding_ms = int(self.job["gcd_rounding_ms"])
        self._lock_gcd_s = float(self.job["anim_lock_gcd_s"])
        self._lock_ogcd_s = float(self.job["anim_lock_ogcd_s"])
        self._server_tick_s = float(self.job["server_tick_s"])
        # The client queues a weaponskill requested inside this window and fires it
        # the instant the recast ends (CielBard_Rotation.lua:1006-1021).
        self._queue_window_us = int(round(float(self.job["gcd_queue_window_s"]) * US))
        self._auto_interval_s = float(self.job["auto_attack_interval_s"])
        self._proc_chance = float(self.job["repertoire_proc_chance"])
        self._sv_per_proc = int(self.job["soul_voice_per_repertoire"])
        self._sv_max = int(self.job["soul_voice_max"])
        self._pp_max = int(self.job["pitch_perfect_max_stacks"])
        self._pp_potency = list(self.job["pitch_perfect_potency"])
        self._paeon_max = int(self.job["army_paeon_max_stacks"])
        self._paeon_haste = float(self.job["army_paeon_haste_per_stack_pct"])
        self._muse_haste = list(self.job["army_muse_haste_by_stacks_pct"])
        self._ballad_reduction_s = float(self.job["ballad_charge_reduction_s"])
        self._song_duration_s = float(self.job["song_duration_s"])
        self._coda_mult = list(self.job["coda_damage_mult"])
        self._encore_potency = list(self.job["radiant_encore_potency"])
        self._apex = dict(self.job["apex"])
        self._apex_min = float(self._apex["gauge_min"])
        self._blast_threshold = float(self._apex["blast_gauge_threshold"])
        self._potion_mult = float(self.stats.get("potion_damage_mult", 1.0))
        self._auto_dps = float(self.stats.get("auto_attack_dps", 0.0))
        self._hawks_eye_chance = float(self.job["hawks_eye_proc_chance"])
        # Statuses that make the next damaging weaponskill land more than once
        # (Barrage: three hits). Read from `statuses.json` rather than named here,
        # so the mechanic stays in the tables.
        self._multi_hit_statuses: Tuple[str, ...] = tuple(
            key for key in sorted(self.tables.statuses)
            if self.tables.statuses[key].weaponskill_hits > 1
        )
        self._army_ethos_s = float(self.job["army_ethos_s"])
        self._damage_delay_us = int(float(self.job.get("damage_delay_s", 0.0)) * US)
        # MECHANICS_CORRECTIONS.md 1: procs roll every `server_tick_s` on the song
        # timer, at 80 %, with no roll in the song's final tick, and - this is the
        # modelling assumption, not an observed fact - independently of the DoTs.
        # `repertoire_independent_of_dots` defaults to True and is the flag that
        # turns the assumption off; the pre-correction key `repertoire_requires_dot`
        # is still honoured as its inverse so old override files keep working.
        self._repertoire_on_song_timer = bool(self.job.get("repertoire_on_song_timer", True))
        independent = self.job.get("repertoire_independent_of_dots")
        if independent is None:
            independent = not bool(self.job.get("repertoire_requires_dot", False))
        self._repertoire_independent_of_dots = bool(independent)
        self._repertoire_skip_final_tick = bool(
            self.job.get("repertoire_skip_final_tick", True)
        )
        self._level_sync_disabled = frozenset(
            self.job.get("level_sync_disabled", LEVEL_SYNC_DISABLED)
        )
        self._potion_hqid = int(self.job.get("potion_hqid", DEFAULT_POTION_HQID))

        # --- game state ---------------------------------------------------
        self.anim_lock_until_us: int = 0
        self.gcd_ready_us: int = 0
        self.current_gcd_s: float = self._gcd_base_s
        self.cooldown_ready_us: Dict[str, int] = {}
        self.player_statuses: Dict[str, StatusInstance] = {}
        self.entity_statuses: Dict[int, Dict[str, StatusInstance]] = {}
        self.soul_voice: int = 0
        self.repertoire: int = 0
        self.paeon_stacks: int = 0
        self.ballad_procs: int = 0
        self.codas: Set[str] = set()
        self.song: Optional[str] = None
        self.song_ends_us: int = 0
        self.song_epoch: int = 0
        self.coda_count_for_finale: int = 0
        self.last_cast_id: int = 0
        self.last_cast_us: int = -10 * US
        self.casts: List[CastRecord] = []
        self.damage_events: List[DamageRecord] = []
        self.rejections: List[CoreRejection] = []
        self.wasted_procs: Dict[str, int] = {
            "repertoire_overcap": 0,
            "soul_voice_overcap": 0,
            "hawks_eye_overwritten": 0,
            "charge_overcap": 0,
        }
        self._client_rejections: List[ClientRejection] = []
        self._warnings: Tuple[str, ...] = ()
        self._fight_over: bool = False
        self._downtime_active: bool = False
        self._pulses: int = 0
        self._trace_lines: List[str] = []

        # --- charge pool ---------------------------------------------------
        self._charge_keys: List[str] = sorted(
            k for k, a in self.tables.actions.items() if a.max_charges > 1
        )
        if self._charge_keys:
            pool = self.tables.action(self._charge_keys[0])
            self._charge_max = int(pool.max_charges)
            # `recast_s` is the per-charge recast (15 s); `cooldown_s` is the full
            # stack the live client reports as cdmax (45 s).
            if pool.recast_s > 0:
                self._charge_recast_s = float(pool.recast_s)
            else:
                self._charge_recast_s = float(pool.cooldown_s) / self._charge_max
        else:  # pragma: no cover - the shipped tables always carry the pool
            self._charge_recast_s = 15.0
            self._charge_max = 3
        self._charge_cap_s = self._charge_recast_s * self._charge_max
        self._charge_anchor_us: int = -int(self._charge_cap_s * US)

        # --- derived per-action bookkeeping ---------------------------------
        self._build_action_groups()

        # --- entities and mirror views ---------------------------------------
        self.entities: List[EntityView] = []
        self._build_entities()
        self._player_view = PlayerView(id=self.player_id, job=23)
        self._potion_view: Optional[PotionView] = None
        self._potion_ready_us: int = 0

        # --- uptime accounting -------------------------------------------------
        self._dot_open: Dict[str, int] = {}
        self._dot_total_us: Dict[str, int] = {}
        self._song_open: Optional[Tuple[str, int]] = None
        self._song_total_us: Dict[str, int] = {code: 0 for code in SONG_ORDER}
        self._song_casts: Dict[str, int] = {code: 0 for code in SONG_ORDER}
        self._gcd_casts: List[Tuple[int, int]] = []

        self.client: Optional[FakeClient] = None
        # `recasttime` for the GCD group, as last written to the client. The live
        # client reports the *hasted* recast, so it is republished on every change.
        self._published_gcd_s: float = self._gcd_base_s

        # Auto attacks are a flat DPS line, so they are expressed as the potency that
        # produces `auto_attack_dps` at the model's own unbuffed expectation; rolling
        # that potency with the live snapshot then scales them by the same buffs the
        # rotation gets. A zero `auto_attack_dps` schedules nothing at all.
        self._auto_potency: int = 0
        if self._auto_dps > 0.0 and self._auto_interval_s > 0.0:
            per_potency = self.damage_model.expected(1000, BuffSnapshot()) / 1000.0
            if per_potency > 0.0:
                self._auto_potency = int(
                    round(self._auto_dps * self._auto_interval_s / per_potency)
                )

    # ------------------------------------------------------------------
    # construction helpers
    # ------------------------------------------------------------------
    def _apply_job_overrides(self, overrides: Dict[str, Any]) -> None:
        """Merge `FightConfig.job_overrides` into `self.job` with job.json's own checks.

        A `None` value deletes the key, which is how an override restores the legacy
        `repertoire_requires_dot` path; every other key must already exist in
        `job.json` or be one of `LEGACY_JOB_KEYS` / `CORE_ONLY_JOB_KEYS`, and the
        merged table is handed back to `sim.tables._validate_job`. Without this a
        misspelled override (the docs point at `repertoire_independent_of_dots`) was
        accepted silently, left the default in place, and reported a clean run that
        tested nothing.
        """
        allowed_extras = LEGACY_JOB_KEYS | CORE_ONLY_JOB_KEYS
        unknown = sorted(
            key for key in overrides
            if key not in self.tables.job and key not in allowed_extras
        )
        if unknown:
            raise SimConfigError(
                "unknown job_overrides key(s): " + ", ".join(unknown)
                + "; job.json defines " + ", ".join(sorted(self.tables.job))
                + " (plus " + ", ".join(sorted(allowed_extras)) + ")"
            )
        for key, value in overrides.items():
            if value is None:
                self.job.pop(key, None)
            else:
                self.job[key] = value
        try:
            _validate_job(self.job)
        except SimDataError as exc:
            raise SimConfigError(f"job_overrides: {exc}") from exc

    def _build_action_groups(self) -> None:
        """Partition the action table into the groups `sync_client` updates per pulse."""
        self._views: Dict[int, ActionView] = {}
        self._specs: List[ActionSpec] = []
        self._key_by_id: Dict[int, str] = {}
        gcd_group: List[Tuple[str, ActionData, ActionView]] = []
        charge_group: List[Tuple[str, ActionData, ActionView]] = []
        other_group: List[Tuple[str, ActionData, ActionView]] = []
        for key in sorted(self.tables.actions):
            data = self.tables.action(key)
            view = ActionView()
            self._views[data.id] = view
            self._key_by_id[data.id] = key
            recast = self._spec_recast_s(key, data)
            self._specs.append(
                ActionSpec(
                    action_id=data.id,
                    name=data.name,
                    is_gcd=data.is_gcd,
                    self_target=data.self_target,
                    recast_s=recast,
                    max_charges=data.max_charges,
                    status_gained_id=data.status_gained_id,
                )
            )
            if key == KEY_POTION:
                continue
            if data.is_gcd:
                gcd_group.append((key, data, view))
            elif key in self._charge_keys:
                charge_group.append((key, data, view))
            else:
                other_group.append((key, data, view))
        self._gcd_group = gcd_group
        self._charge_group = charge_group
        self._other_group = other_group

    def _spec_recast_s(self, key: str, data: ActionData) -> float:
        """The static `recasttime` the client reports for one action."""
        if data.is_gcd:
            return float(data.recast_s or self._gcd_base_s)
        if key in self._charge_keys:
            return float(self._charge_recast_s)
        if data.cooldown_s > 0:
            return float(data.cooldown_s)
        return float(data.recast_s)

    def _build_entities(self) -> None:
        """Create the primary target and its clones, all within AoE range of each other."""
        self.entities = []
        for index in range(max(1, int(self.config.enemies))):
            entity_id = self.target_id if index == 0 else self._clone_base_id + index - 1
            view = EntityView(id=entity_id, name=f"Striking Dummy {index + 1}")
            self.entities.append(view)
            self.entity_statuses[entity_id] = {}

    # ------------------------------------------------------------------
    # clock
    # ------------------------------------------------------------------
    def now_us(self) -> int:
        """The simulation clock in microseconds."""
        return self._us

    def now_ms(self) -> int:
        """The simulation clock in whole milliseconds, as `Now()` reports it."""
        return self._us // 1000

    def now_s(self) -> float:
        """The simulation clock in seconds."""
        return self._us / float(US)

    # ------------------------------------------------------------------
    # run loop
    # ------------------------------------------------------------------
    def run(self) -> FightResult:
        """Run to completion and return the result. Always closes the client."""
        repo_root = self.config.resolved_repo_root()
        self.client = FakeClient(
            repo_root,
            self._specs,
            player_id=self.player_id,
            target_id=self.target_id,
        )
        errors: List[str] = []
        try:
            self.client.init_engine(self.config.engine_overrides())
            self._warm_inventory()
            self._warnings = tuple(self.client.warnings())
            self._schedule_initial()
            self._loop()
            engine_state = dict(self.client.engine_state())
        finally:
            if self.client is not None:
                errors = list(self.client.errors)
                self.client.close()
        if errors:
            raise SimulationError(
                "client callbacks raised during the fight: " + "; ".join(errors[:5])
            )
        return self._build_result(engine_state)

    def _warm_inventory(self) -> None:
        """Publish the potion before the first pulse and force the engine to scan it.

        `Now()` starts at 0, so the engine's own five-second inventory-scan throttle
        (`E.RefreshPotion`) would otherwise report "no potion" for the first 5 s of
        every fight and raise a spurious configuration warning. A live client has
        been running for hours, so the scan is forced once here instead.
        """
        client = self.client
        if client is None or not self.config.use_potion:
            return
        client.set_time(0)
        client.set_potions(self._potions(0))
        engine = getattr(client, "engine", None)
        refresh = getattr(engine, "RefreshPotion", None) if engine is not None else None
        if refresh is not None:
            refresh(True)

    def _schedule_initial(self) -> None:
        """Queue the server tick grid, the downtime windows and the fight end."""
        if self.config.tick_offset_s is None:
            offset = self.rng.stream("tick_offset").uniform(0.0, self._server_tick_s)
        else:
            offset = float(self.config.tick_offset_s)
        offset = offset % self._server_tick_s
        first = int(round(offset * US))
        if first <= 0:
            first = int(round(self._server_tick_s * US))
        self.queue.push_kind(first, SERVER_TICK, scope="world")
        if self._auto_potency > 0:
            step = int(round(self._auto_interval_s * US))
            if step > 0:
                self.queue.push_kind(step, AUTO_ATTACK)
        for window in self.config.downtime:
            self.queue.push_kind(int(round(window.start_s * US)), DOWNTIME_START)
            self.queue.push_kind(int(round(window.end_s * US)), DOWNTIME_END)
        self.queue.push_kind(self.end_us, FIGHT_END)

    def _loop(self) -> None:
        """The pulse loop of SPEC 6.5. Time advances only here."""
        pulse_us = self.pulse_us
        end_us = self.end_us
        client = self.client
        assert client is not None
        fast_skip = bool(self.config.fast_skip_locked)
        t = 0
        while t <= end_us:
            self._us = t
            for event in self.queue.pop_due(t):
                self._handle(event)
            if not self._fight_over:
                locked = self.anim_lock_until_us > t
                if not (fast_skip and locked):
                    self._sync_client(t)
                    client.step()
                    self._pulses += 1
                    requests = client.take_requests()
                    if len(requests) > MAX_REQUESTS_PER_PULSE:
                        raise SimulationError(
                            f"engine issued {len(requests)} requests in one pulse at "
                            f"{t / US:.3f}s (limit {MAX_REQUESTS_PER_PULSE})"
                        )
                    for index, request in enumerate(requests):
                        if index == 0:
                            self._resolve(request, t)
                        else:
                            self._reject(t, request.action_id, "multiple-requests-per-pulse")
                    rejections = client.take_rejections()
                    if rejections:
                        self._client_rejections.extend(rejections)
            t += pulse_us
        self._us = end_us
        for event in self.queue.pop_due(end_us):
            self._handle(event)

    # ------------------------------------------------------------------
    # event handling
    # ------------------------------------------------------------------
    def _handle(self, event: Event) -> None:
        """Dispatch one queued event."""
        kind = event.kind
        if kind == SERVER_TICK:
            self._handle_server_tick(event)
        elif kind == AUTO_ATTACK:
            self._handle_auto_attack(event)
        elif kind == STATUS_EXPIRE:
            self._handle_status_expire(event)
        elif kind == ACTION_EXECUTE:
            self._handle_action_execute(event)
        elif kind == DOWNTIME_START:
            self._downtime_active = True
            # The target leaves: its debuffs go with it, so the engine has to
            # re-apply the DoTs when it comes back (SPEC 8.2 invariant 19).
            self._clear_entity_statuses(event.t_us)
        elif kind == DOWNTIME_END:
            self._downtime_active = False
        elif kind == FIGHT_END:
            self._fight_over = True
        # lock_end, gcd_ready and cooldown_ready need no handler: the state they
        # describe is derived from the stored deadlines. They stay scheduled so
        # the queue is a complete, inspectable record of the fight.

    def _handle_server_tick(self, event: Event) -> None:
        """A 3 s tick: DoT damage on the world grid, Repertoire on the song grid."""
        t = event.t_us
        if event.payload.get("scope") == "song":
            if event.payload.get("epoch") == self.song_epoch and self.song is not None:
                self._repertoire_proc(t)
            return
        self._tick_dots(t)
        if not self._repertoire_on_song_timer and self.song is not None:
            self._repertoire_proc(t)
        nxt = t + int(round(self._server_tick_s * US))
        if nxt <= self.end_us:
            self.queue.push_kind(nxt, SERVER_TICK, scope="world")

    def _handle_auto_attack(self, event: Event) -> None:
        """One auto-attack swing, then reschedule. Silent while the target is gone."""
        t = event.t_us
        if not self._downtime_active and self._auto_potency > 0:
            self._deal_damage(t, 0, "AutoAttack", "auto", self._auto_potency, self._snapshot())
        nxt = t + int(round(self._auto_interval_s * US))
        if nxt <= self.end_us:
            self.queue.push_kind(nxt, AUTO_ATTACK)

    def _handle_status_expire(self, event: Event) -> None:
        """Drop a status when the scheduled expiry is still the current one."""
        who = event.payload["who"]
        key = event.payload["key"]
        expires_us = event.payload["expires_us"]
        holder = self.player_statuses if who == PLAYER else self.entity_statuses.get(who)
        if holder is None:
            return
        instance = holder.get(key)
        if instance is None or instance.expires_us != expires_us:
            return
        del holder[key]
        self._on_status_removed(who, key, event.t_us)

    def _on_status_removed(self, who: int, key: str, t_us: int) -> None:
        """Bookkeeping shared by expiry and by an overwriting application."""
        if who == self.target_id:
            start = self._dot_open.pop(key, None)
            if start is not None:
                self._dot_total_us[key] = self._dot_total_us.get(key, 0) + (t_us - start)
        if who == PLAYER and key in SONG_CODES and self.song == SONG_CODES[key]:
            self._end_song(t_us)

    def _handle_action_execute(self, event: Event) -> None:
        """Apply the effects of an action that has landed."""
        payload = event.payload
        t = event.t_us
        key = payload["key"]
        action_id = payload["action_id"]
        target_id = payload["target_id"]
        potency = int(payload["potency"])
        snapshot = self._snapshot()

        if potency > 0:
            record = self.tables.actions.get(key)
            hits = self._consume_multi_hit(record, t)
            for _ in range(hits):
                self._deal_damage(t, action_id, key, "direct", potency, snapshot)
                if record is not None and record.aoe and len(self.entities) > 1:
                    share = record.falloff if record.falloff > 0 else 1.0
                    splash = int(round(potency * share))
                    if splash > 0:
                        for _ in range(len(self.entities) - 1):
                            self._deal_damage(t, action_id, key, "direct", splash, snapshot)

        if key == KEY_POTION:
            self._apply_status(PLAYER, KEY_MEDICATED, t, mult_override=self._potion_mult)
            return

        data = self.tables.action(key)
        # Apex Arrow's BlastArrowReady grant is conditional on the gauge spent, so
        # the core withholds it rather than letting the table apply it blindly.
        skip = None
        if key == KEY_APEX and self.soul_voice < self._blast_threshold:
            skip = (KEY_BLAST_READY,)
        self._apply_grants(data, t, target_id, snapshot, skip=skip)
        self._consume_requires(data, t)
        self._apply_special(key, data, t, target_id, snapshot)

    # ------------------------------------------------------------------
    # resolution
    # ------------------------------------------------------------------
    def _resolve(self, request: CastRequest, t: int) -> None:
        """Accept or reject one cast request the engine issued this pulse."""
        if request.is_item:
            key: Optional[str] = KEY_POTION
        else:
            data_or_none = self.tables.by_id(request.action_id)
            key = data_or_none.key if data_or_none is not None else None
        if key is None:
            self._reject(t, request.action_id, "unknown-action")
            return
        data = self.tables.action(key)
        is_gcd = data.is_gcd and not request.is_item
        if self.anim_lock_until_us > t:
            self._reject(t, request.action_id, "locked")
            return
        # The engine deliberately asks for the next weaponskill slightly early
        # (`gcdLeadSeconds`, CielBard_Rotation.lua:1021) because the live client
        # queues the request and fires it the instant the recast ends. Model that
        # queue: a request inside `gcd_queue_window_s` is accepted and resolved at
        # `gcd_ready_us`; anything further out is still refused.
        t_eff = t
        if is_gcd and self.gcd_ready_us > t:
            if self.gcd_ready_us - t > self._queue_window_us:
                self._reject(t, request.action_id, "gcd-not-ready")
                return
            t_eff = self.gcd_ready_us
        if request.is_item:
            available = bool(self.config.use_potion) and self._potion_ready_us <= t_eff
        else:
            available = self._available(key, data, t_eff)
        if not available:
            self._reject(t, request.action_id, "unavailable")
            return

        lock_s = (self._lock_gcd_s if is_gcd else self._lock_ogcd_s) + self.config.ping_ms / 1000.0
        self.anim_lock_until_us = t_eff + int(round(lock_s * US))
        self.queue.push_kind(self.anim_lock_until_us, LOCK_END)
        if is_gcd:
            gcd_us = int(round(self.current_gcd_s * US))
            self.gcd_ready_us = t_eff + gcd_us
            self.queue.push_kind(self.gcd_ready_us, GCD_READY)
            self._gcd_casts.append((t_eff, gcd_us))
        self._start_cooldown(key, data, t_eff, request.is_item)

        self.last_cast_id = request.action_id
        self.last_cast_us = t_eff
        potency = self._potency_for(key, data)
        decision = self._decision()
        self.casts.append(
            CastRecord(
                t_s=t_eff / float(US),
                action_id=request.action_id,
                key=key,
                name=data.name,
                is_gcd=is_gcd,
                target_id=request.target_id,
                potency=potency,
                decision=decision,
            )
        )
        if self.config.trace:
            self._trace_lines.append(f"{t_eff / US:8.3f}  {key:<16} {decision}")
        self.queue.push_kind(
            t_eff + self._damage_delay_us,
            ACTION_EXECUTE,
            key=key,
            action_id=request.action_id,
            target_id=request.target_id if not request.is_item else self.player_id,
            potency=potency,
        )

    def _reject(self, t: int, action_id: int, reason: str) -> None:
        """Record a request the core refused."""
        self.rejections.append(
            CoreRejection(
                t_s=t / float(US),
                action_id=action_id,
                reason=reason,
                decision=self._decision(),
            )
        )

    def _decision(self) -> str:
        """The engine's `lastDecision` at this pulse, or "" when no client is attached."""
        if self.client is None:
            return ""
        state = self.client.engine_state()
        value = state.get("lastDecision", "")
        return str(value) if value is not None else ""

    def _start_cooldown(self, key: str, data: ActionData, t: int, is_item: bool) -> None:
        """Spend the resource an accepted action costs: a charge, or its own cooldown."""
        if is_item:
            self._potion_ready_us = t + int(round(float(data.cooldown_s) * US))
            self.queue.push_kind(self._potion_ready_us, COOLDOWN_READY, key=KEY_POTION)
            return
        if key in self._charge_keys:
            progress = self._charge_progress_s(t)
            self._set_charge_progress(t, progress - self._charge_recast_s)
            self.queue.push_kind(
                t + int(round(self._charge_recast_s * US)), COOLDOWN_READY, key=key
            )
            return
        if data.cooldown_s > 0:
            ready_at = t + int(round(float(data.cooldown_s) * US))
            self.cooldown_ready_us[key] = ready_at
            self.queue.push_kind(ready_at, COOLDOWN_READY, key=key)

    # ------------------------------------------------------------------
    # charge pool
    # ------------------------------------------------------------------
    def _charge_progress_s(self, t_us: int) -> float:
        """Seconds of recast progress in the shared Heartbreak/Bloodletter/RoD pool."""
        progress = (t_us - self._charge_anchor_us) / float(US)
        if progress > self._charge_cap_s:
            return self._charge_cap_s
        if progress < 0.0:
            return 0.0
        return progress

    def _set_charge_progress(self, t_us: int, progress_s: float) -> None:
        """Move the pool anchor so the pool reads `progress_s` at `t_us`."""
        if progress_s < 0.0:
            progress_s = 0.0
        elif progress_s > self._charge_cap_s:
            progress_s = self._charge_cap_s
        self._charge_anchor_us = t_us - int(round(progress_s * US))

    def charges(self, t_us: int) -> int:
        """The number of whole charges available in the shared pool."""
        return int(self._charge_progress_s(t_us) // self._charge_recast_s)

    def _advance_charges(self, t_us: int, seconds: float) -> None:
        """Mage's Ballad Repertoire: push the pool forward, counting the overflow."""
        progress = self._charge_progress_s(t_us)
        if progress + seconds > self._charge_cap_s:
            self.wasted_procs["charge_overcap"] += 1
        self._set_charge_progress(t_us, progress + seconds)

    # ------------------------------------------------------------------
    # statuses
    # ------------------------------------------------------------------
    def _apply_status(
        self,
        who: int,
        key: str,
        t_us: int,
        *,
        duration_s: Optional[float] = None,
        snapshot: Optional[BuffSnapshot] = None,
        stacks: int = 1,
        mult_override: Optional[float] = None,
        codas: int = 0,
    ) -> StatusInstance:
        """Apply or refresh one status, scheduling its expiry."""
        data = self.tables.status(key)
        holder = self.player_statuses if who == PLAYER else self.entity_statuses.setdefault(who, {})
        existing = holder.get(key)
        carried = existing.snapshot if existing is not None else None
        if key == KEY_HAWKS_EYE and existing is not None:
            self.wasted_procs["hawks_eye_overwritten"] += 1
        duration = float(data.duration_s if duration_s is None else duration_s)
        expires_us = t_us + int(round(duration * US))
        instance = StatusInstance(
            key=key,
            expires_us=expires_us,
            stacks=stacks,
            snapshot=snapshot if snapshot is not None else carried,
            mult_override=mult_override,
            codas=codas,
        )
        holder[key] = instance
        self.queue.push_kind(expires_us, STATUS_EXPIRE, who=who, key=key, expires_us=expires_us)
        if who == self.target_id and data.dot_potency > 0 and key not in self._dot_open:
            self._dot_open[key] = t_us
        return instance

    def _remove_status(self, who: int, key: str, t_us: int) -> None:
        """Drop a status before its expiry (song swap, resource consumption)."""
        holder = self.player_statuses if who == PLAYER else self.entity_statuses.get(who)
        if holder is None or key not in holder:
            return
        del holder[key]
        if who == self.target_id:
            start = self._dot_open.pop(key, None)
            if start is not None:
                self._dot_total_us[key] = self._dot_total_us.get(key, 0) + (t_us - start)

    def _clear_entity_statuses(self, t_us: int) -> None:
        """Drop every status on every entity, closing the DoT uptime intervals."""
        for entity in self.entities:
            holder = self.entity_statuses.get(entity.id)
            if not holder:
                continue
            for key in sorted(holder):
                self._remove_status(entity.id, key, t_us)

    def _has(self, key: str) -> bool:
        """True when the player currently has `key`."""
        return key in self.player_statuses

    def _snapshot(self) -> BuffSnapshot:
        """Multipliers frozen from the player's current statuses (SPEC 6.10)."""
        mult = 1.0
        crit_add = 0.0
        dh_add = 0.0
        status_of = self.tables.status
        for key, instance in self.player_statuses.items():
            data = status_of(key)
            override = instance.mult_override
            mult *= override if override is not None else data.damage_mult
            crit_add += data.crit_add
            dh_add += data.dh_add
        return BuffSnapshot(damage_mult=mult, crit_add=crit_add, dh_add=dh_add)

    # ------------------------------------------------------------------
    # damage
    # ------------------------------------------------------------------
    def _deal_damage(
        self, t_us: int, action_id: int, key: str, source: str, potency: int, snap: BuffSnapshot
    ) -> None:
        """Roll one damage instance and record it.

        In the expected-value mode (`FightConfig.deterministic_damage`) the closed
        form replaces the roll, so no crit, direct-hit or variance randomness is
        consumed and the record carries the expected multiplier with both flags off.
        """
        if self.profile.expected_value:
            amount = self.damage_model.expected(potency, snap)
            scale = float(potency) * self.profile.potency_to_damage
            self.damage_events.append(
                DamageRecord(
                    t_s=t_us / float(US),
                    action_id=action_id,
                    key=key,
                    source=source,
                    potency=int(potency),
                    amount=float(amount),
                    crit=False,
                    direct_hit=False,
                    multiplier=float(amount / scale) if scale else 0.0,
                )
            )
            return
        result = self.damage_model.roll(potency, snap)
        self.damage_events.append(
            DamageRecord(
                t_s=t_us / float(US),
                action_id=action_id,
                key=key,
                source=source,
                potency=int(result.potency),
                amount=float(result.amount),
                crit=bool(result.crit),
                direct_hit=bool(result.direct_hit),
                multiplier=float(result.multiplier),
            )
        )

    def _tick_dots(self, t_us: int) -> None:
        """Roll one tick for every active DoT, on every entity."""
        status_of = self.tables.status
        for entity in self.entities:
            holder = self.entity_statuses.get(entity.id)
            if not holder:
                continue
            for key in sorted(holder):
                instance = holder[key]
                data = status_of(key)
                if data.dot_potency <= 0:
                    continue
                snap = instance.snapshot if instance.snapshot is not None else BuffSnapshot()
                action = self.tables.actions.get(key)
                action_id = action.id if action is not None else 0
                self._deal_damage(t_us, action_id, key, "dot", data.dot_potency, snap)

    # ------------------------------------------------------------------
    # action effects
    # ------------------------------------------------------------------
    def _apply_grants(
        self,
        data: ActionData,
        t_us: int,
        target_id: int,
        snapshot: BuffSnapshot,
        skip: Optional[Sequence[str]] = None,
    ) -> None:
        """Apply the statuses an action grants, rolling any sub-100 % chance.

        Hawk's Eye is the one rate the job table owns: `job.hawks_eye_proc_chance` is
        the single source of truth for every *probabilistic* Hawk's Eye grant (Burst
        Shot, Stormbite, Caustic Bite, Iron Jaws, Ladonsbite), so a sweep or a
        `job_overrides` entry moves every proc source at once instead of silently
        doing nothing.  A grant the table writes as certain stays certain:
        MECHANICS_CORRECTIONS.md 7 makes Barrage's Hawk's Eye guaranteed, and it
        must not be dragged down to the proc rate.
        """
        hawks_eye_chance = self._hawks_eye_chance
        for grant in data.grants:
            if skip is not None and grant.status in skip:
                continue
            if grant.status == KEY_HAWKS_EYE and float(grant.chance) < 1.0:
                chance = hawks_eye_chance
            else:
                chance = float(grant.chance)
            if chance < 1.0:
                if self.rng.stream("hawks_eye").random() >= chance:
                    continue
            status = self.tables.status(grant.status)
            who = target_id if status.on_target else PLAYER
            self._apply_status(
                who,
                grant.status,
                t_us,
                duration_s=grant.duration_s,
                snapshot=snapshot if status.dot_potency > 0 else None,
            )

    def _consume_multi_hit(self, data: Optional[ActionData], t_us: int) -> int:
        """How many times this cast lands, spending any multi-hit status.

        Barrage makes the *next eligible weaponskill* hit `weaponskill_hits` times
        (3, so a 280-potency Refulgent Arrow is worth 840) and is consumed by it.
        The hit count lives in `statuses.json` and eligibility in `actions.json`
        (`multi_hit_eligible`: Burst Shot, Refulgent Arrow, Ladonsbite, Shadowbite
        and their level-sync precursors), so no Barrage constant appears here. An
        off-GCD, the potion or an ineligible weaponskill - Resonant Arrow, Apex, the
        DoTs, Radiant Encore - neither benefits nor consumes the buff; the engine
        casts Resonant Arrow between Barrage and the Refulgent Arrow, so that
        distinction is what makes MECHANICS_CORRECTIONS.md item 15 reachable.
        """
        if data is None or not data.is_gcd or not data.multi_hit_eligible:
            return 1
        for key in self._multi_hit_statuses:
            if key in self.player_statuses:
                self._remove_status(PLAYER, key, t_us)
                return int(self.tables.statuses[key].weaponskill_hits)
        return 1

    def _consume_requires(self, data: ActionData, t_us: int) -> None:
        """Remove the statuses an action consumes."""
        for key in data.requires:
            self._remove_status(PLAYER, key, t_us)

    def _apply_special(
        self, key: str, data: ActionData, t_us: int, target_id: int, snapshot: BuffSnapshot
    ) -> None:
        """Resource and mechanic side effects that are not plain status grants."""
        if key in SONG_CODES:
            self._start_song(SONG_CODES[key], t_us)
            return
        if key == KEY_APEX:
            if self.soul_voice >= self._blast_threshold and not self._has(KEY_BLAST_READY):
                self._apply_status(PLAYER, KEY_BLAST_READY, t_us)
            self.soul_voice = 0
            return
        if key == KEY_PITCH_PERFECT:
            self.repertoire = 0
            return
        if key == KEY_EMPYREAL:
            self._repertoire_proc(t_us, guaranteed=True)
            return
        if key == KEY_FINALE:
            count = max(0, min(len(self.codas), len(self._coda_mult) - 1))
            self.coda_count_for_finale = count
            self.codas.clear()
            self._apply_status(
                PLAYER, KEY_FINALE, t_us, mult_override=float(self._coda_mult[count])
            )
            self._apply_status(PLAYER, KEY_ENCORE_READY, t_us, codas=count)
            return
        if key == KEY_IRON_JAWS:
            self._iron_jaws(
                t_us, target_id, snapshot, already=[g.status for g in data.grants]
            )
            return

    def _iron_jaws(
        self,
        t_us: int,
        target_id: int,
        snapshot: BuffSnapshot,
        already: Optional[Sequence[str]] = None,
    ) -> None:
        """Refresh every DoT already on the target to full duration, re-snapshotting.

        Iron Jaws never *applies* a DoT: on a clean target it is a bare 100-potency
        weaponskill, which is why `actions.json` grants it nothing but Hawk's Eye.
        `already` names the statuses the action's own `grants` have handled, so a
        data table that does list a DoT does not get it applied twice.
        """
        holder = self.entity_statuses.setdefault(target_id, {})
        done = set(already or ())
        for key in sorted(holder):
            if key not in done and self.tables.status(key).dot_potency > 0:
                self._apply_status(target_id, key, t_us, snapshot=snapshot)

    # ------------------------------------------------------------------
    # songs, Repertoire, Soul Voice
    # ------------------------------------------------------------------
    def _start_song(self, code: str, t_us: int) -> None:
        """Start a song: end the previous one, apply the status, schedule its ticks."""
        self._end_song(t_us)
        ethos = self.player_statuses.get(KEY_ETHOS)
        if ethos is not None:
            stacks = max(1, min(ethos.stacks, len(self._muse_haste)))
            self._remove_status(PLAYER, KEY_ETHOS, t_us)
            self._apply_status(PLAYER, KEY_MUSE, t_us, stacks=stacks)
        self.song = code
        self.song_epoch += 1
        self.repertoire = 0
        self.ballad_procs = 0
        self.codas.add(code)
        duration = self._song_duration_s
        self.song_ends_us = t_us + int(round(duration * US))
        self._apply_status(PLAYER, SONG_KEYS[code], t_us, duration_s=duration)
        self._song_open = (code, t_us)
        self._song_casts[code] = self._song_casts.get(code, 0) + 1
        if self._repertoire_on_song_timer:
            step_us = int(round(self._server_tick_s * US))
            tick_us = t_us + step_us
            # MECHANICS_CORRECTIONS.md 1: rolls at 42, 39, ... 3 s remaining; no
            # roll in the final `server_tick_s` of the song.
            last_us = self.song_ends_us - (step_us if self._repertoire_skip_final_tick else 0)
            while tick_us <= last_us:
                self.queue.push_kind(tick_us, SERVER_TICK, scope="song", epoch=self.song_epoch)
                tick_us += step_us

    def _end_song(self, t_us: int) -> None:
        """End the current song, converting Army's Paeon stacks into Army's Ethos."""
        if self.song is None:
            return
        code = self.song
        if code == "AP" and self.paeon_stacks > 0:
            self._apply_status(
                PLAYER, KEY_ETHOS, t_us,
                duration_s=self._army_ethos_s, stacks=self.paeon_stacks,
            )
        self.paeon_stacks = 0
        self.repertoire = 0
        self.ballad_procs = 0
        self.song = None
        self.song_ends_us = t_us
        self.song_epoch += 1
        if self._song_open is not None:
            open_code, start = self._song_open
            self._song_total_us[open_code] = self._song_total_us.get(open_code, 0) + (t_us - start)
            self._song_open = None
        key = SONG_KEYS[code]
        if key in self.player_statuses:
            del self.player_statuses[key]

    def _any_dot_on_target(self) -> bool:
        """True when at least one of our DoTs is on the primary target."""
        holder = self.entity_statuses.get(self.target_id)
        if not holder:
            return False
        for key in holder:
            if self.tables.status(key).dot_potency > 0:
                return True
        return False

    def _repertoire_proc(self, t_us: int, *, guaranteed: bool = False) -> bool:
        """Roll (or force) one Repertoire proc and apply its song-specific effect."""
        if self.song is None:
            return False
        if not guaranteed:
            if not self._repertoire_independent_of_dots and not self._any_dot_on_target():
                return False
            if self.rng.stream("repertoire").random() >= self._proc_chance:
                return False
        gain = self._sv_per_proc
        if self.soul_voice + gain > self._sv_max:
            self.wasted_procs["soul_voice_overcap"] += self.soul_voice + gain - self._sv_max
            self.soul_voice = self._sv_max
        else:
            self.soul_voice += gain
        code = self.song
        if code == "WM":
            if self.repertoire >= self._pp_max:
                self.wasted_procs["repertoire_overcap"] += 1
            else:
                self.repertoire += 1
        elif code == "MB":
            self.ballad_procs += 1
            self._advance_charges(t_us, self._ballad_reduction_s)
        elif code == "AP":
            if self.paeon_stacks >= self._paeon_max:
                self.wasted_procs["repertoire_overcap"] += 1
            else:
                self.paeon_stacks += 1
        return True

    # ------------------------------------------------------------------
    # availability
    # ------------------------------------------------------------------
    def _haste_pct(self) -> float:
        """The current GCD haste percentage from Army's Paeon or Army's Muse."""
        if self.song == "AP" and self.paeon_stacks > 0:
            return self.paeon_stacks * self._paeon_haste
        muse = self.player_statuses.get(KEY_MUSE)
        if muse is not None:
            index = max(1, min(muse.stacks, len(self._muse_haste))) - 1
            return float(self._muse_haste[index])
        return 0.0

    def _update_gcd(self) -> None:
        """Recompute the current GCD recast from the active haste."""
        self.current_gcd_s = gcd_recast(self._gcd_base_s, self._haste_pct(), self._gcd_rounding_ms)

    def _usable(self, key: str, data: ActionData) -> bool:
        """`ActionView.usable`: level sync and required statuses."""
        if key in self._level_sync_disabled:
            return False
        for requirement in data.requires:
            if requirement not in self.player_statuses:
                return False
        return True

    def _resource_ok(self, key: str) -> bool:
        """Gauge-side gates that `usable` does not already cover."""
        if key == KEY_APEX:
            return self.soul_voice >= self._apex_min
        if key == KEY_PITCH_PERFECT:
            return self.song == "WM" and self.repertoire >= 1
        return True

    def _cooldown_remaining_s(self, key: str, data: ActionData, t_us: int) -> float:
        """Seconds until `key` comes off its own cooldown (0 for GCD-only actions)."""
        if key in self._charge_keys:
            return max(0.0, self._charge_recast_s - self._charge_progress_s(t_us))
        ready_at = self.cooldown_ready_us.get(key, 0)
        if ready_at <= t_us:
            return 0.0
        return (ready_at - t_us) / float(US)

    def _available(self, key: str, data: ActionData, t_us: int) -> bool:
        """Everything but the animation lock and the GCD: usable, resource, cooldown."""
        if not self._usable(key, data):
            return False
        if not self._resource_ok(key):
            return False
        return self._cooldown_remaining_s(key, data, t_us) <= 0.0

    def _gcd_remaining_s(self, t_us: int) -> float:
        """Seconds until the global cooldown is available."""
        if self.gcd_ready_us <= t_us:
            return 0.0
        return (self.gcd_ready_us - t_us) / float(US)

    def _update_views(self, t_us: int) -> None:
        """Fill every `ActionView` for this pulse (SPEC 6.7)."""
        gcd_remaining = self._gcd_remaining_s(t_us)
        gcd_on = gcd_remaining > 0.0
        gcd_max = self.current_gcd_s if gcd_on else 0.0
        gcd_cd = (self.current_gcd_s - gcd_remaining) if gcd_on else 0.0
        for key, data, view in self._gcd_group:
            usable = self._usable(key, data)
            view.usable = usable
            view.cd = gcd_cd
            view.cdmax = gcd_max
            view.isoncd = gcd_on
            view.highlighted = usable and bool(data.requires)
            # `IsReady` does not reflect the recast on live clients
            # (CielBard_Rotation.lua:1006-1007), which is why `E.GCDRemaining` reads
            # cd/cdmax instead. `cd`/`cdmax`/`isoncd` above still carry the recast.
            view.ready = usable and self._resource_ok(key)

        progress = self._charge_progress_s(t_us)
        full = progress >= self._charge_cap_s
        charge_cd = 0.0 if full else progress
        charge_max = 0.0 if full else self._charge_cap_s
        charge_ready = progress >= self._charge_recast_s
        for key, data, view in self._charge_group:
            usable = self._usable(key, data)
            view.usable = usable
            view.cd = charge_cd
            view.cdmax = charge_max
            view.isoncd = not full
            view.highlighted = False
            view.ready = usable and charge_ready

        for key, data, view in self._other_group:
            usable = self._usable(key, data)
            remaining = self._cooldown_remaining_s(key, data, t_us)
            on_cd = remaining > 0.0
            view.usable = usable
            view.cd = (float(data.cooldown_s) - remaining) if on_cd else 0.0
            view.cdmax = float(data.cooldown_s) if on_cd else 0.0
            view.isoncd = on_cd
            view.highlighted = usable and bool(data.requires)
            view.ready = usable and not on_cd and self._resource_ok(key)

    # ------------------------------------------------------------------
    # client mirror
    # ------------------------------------------------------------------
    def _target_hp_percent(self, t_us: int) -> float:
        """The target's HP percentage at `t_us`, which is all the engine's TTK sees.

        With `config.kill_time_s` set this is SPEC 6.6's linear dummy, whose HP
        reaches zero at `kill_time_s`. With it unset the target is a striking dummy
        that never dies (SPEC 1), so the engine never enters its terminal band and
        never stops refreshing DoTs near the end of a short fight.
        """
        kill_time = self.config.kill_time_s
        if kill_time is None:
            return FULL_HP_PERCENT
        return max(0.0, FULL_HP_PERCENT * (1.0 - (t_us / float(US)) / float(kill_time)))

    def _in_downtime(self, t_us: int) -> bool:
        """True while the target is untargetable."""
        return self._downtime_active

    def _gauge(self, t_us: int) -> Tuple[float, float, float, float, float]:
        """The five gauge slots the engine reads (SPEC 3.6)."""
        song_index = 0
        song_remaining = 0.0
        if self.song is not None:
            song_index = SONG_ORDER.index(self.song) + 1
            song_remaining = max(0.0, (self.song_ends_us - t_us) / float(US))
        if self.song == "WM":
            repertoire = self.repertoire
        elif self.song == "AP":
            repertoire = self.paeon_stacks
        elif self.song == "MB":
            # Mage's Ballad grants no Repertoire stacks, so the live gauge byte is 0.
            # `ballad_procs` stays internal (it only feeds the charge pool).
            repertoire = 0
        else:
            repertoire = 0
        mask = 0
        for index, code in enumerate(SONG_ORDER):
            if code in self.codas:
                mask |= 1 << index
        return (song_index, repertoire, int(song_remaining), self.soul_voice, mask)

    def _player_buffs(self, t_us: int) -> Tuple[BuffView, ...]:
        """The player's buff table as the client publishes it."""
        buffs: List[BuffView] = []
        status_of = self.tables.status
        pid = self.player_id
        for key in sorted(self.player_statuses):
            instance = self.player_statuses[key]
            status_id = status_of(key).id
            if not status_id:
                continue
            buffs.append(
                BuffView(
                    id=status_id,
                    ownerid=pid,
                    duration=max(0.0, (instance.expires_us - t_us) / float(US)),
                )
            )
        return tuple(buffs)

    def _entity_buffs(self, entity_id: int, t_us: int) -> Tuple[BuffView, ...]:
        """One entity's debuff table as the client publishes it."""
        holder = self.entity_statuses.get(entity_id)
        if not holder:
            return ()
        status_of = self.tables.status
        pid = self.player_id
        buffs: List[BuffView] = []
        for key in sorted(holder):
            instance = holder[key]
            status_id = status_of(key).id
            if not status_id:
                continue
            buffs.append(
                BuffView(
                    id=status_id,
                    ownerid=pid,
                    duration=max(0.0, (instance.expires_us - t_us) / float(US)),
                )
            )
        return tuple(buffs)

    def _sync_client(self, t_us: int) -> None:
        """Write the whole mirror of game state for this pulse (SPEC 6.6)."""
        client = self.client
        assert client is not None
        client.set_time(t_us // 1000)
        self._update_gcd()
        # The live client reports the *hasted* recast in `recasttime`, so the GCD
        # group is republished whenever Army's Paeon / Army's Muse moves the GCD.
        # That is a handful of writes per fight, not one per pulse.
        if self.current_gcd_s != self._published_gcd_s:
            for _key, data, _view in self._gcd_group:
                client.set_recast(data.id, self.current_gcd_s)
            self._published_gcd_s = self.current_gcd_s

        player = self._player_view
        player.locked = self.anim_lock_until_us > t_us
        player.casting = False
        player.loading = False
        player.incombat = True
        player.alive = True
        player.hp_percent = FULL_HP_PERCENT
        player.gauge = self._gauge(t_us)
        player.buffs = self._player_buffs(t_us)
        client.set_player(player)

        if self._in_downtime(t_us):
            client.set_target(None)
            client.set_entities(())
        else:
            hp_percent = self._target_hp_percent(t_us)
            for entity in self.entities:
                entity.hp_percent = hp_percent
                entity.hp_current = entity.hp_max * hp_percent / 100.0
                entity.buffs = self._entity_buffs(entity.id, t_us)
            client.set_target(self.entities[0])
            client.set_entities(self.entities)

        self._update_views(t_us)
        client.set_actions(self._views)
        # A queued weaponskill has `last_cast_us` in the future until it fires; the
        # live client would report 0, never a negative age.
        client.set_last_cast(self.last_cast_id, max(0, t_us - self.last_cast_us) // 1000)
        if self.config.use_potion:
            client.set_potions(self._potions(t_us))

    def _potions(self, t_us: int) -> Sequence[PotionView]:
        """The single Gemdraught the engine may weave before Raging Strikes."""
        data = self.tables.action(KEY_POTION)
        on_cd = self._potion_ready_us > t_us
        remaining = (self._potion_ready_us - t_us) / float(US) if on_cd else 0.0
        view = PotionView(
            hqid=self._potion_hqid,
            action_id=data.id,
            ready=not on_cd,
            cd=(float(data.cooldown_s) - remaining) if on_cd else 0.0,
            cdmax=float(data.cooldown_s) if on_cd else 0.0,
        )
        self._potion_view = view
        return (view,)

    # ------------------------------------------------------------------
    # results
    # ------------------------------------------------------------------
    def _close_open_intervals(self) -> None:
        """Close DoT and song uptime intervals still open at the end of the fight."""
        end = self.end_us
        for key, start in list(self._dot_open.items()):
            instance = self.entity_statuses.get(self.target_id, {}).get(key)
            stop = min(end, instance.expires_us) if instance is not None else end
            self._dot_total_us[key] = self._dot_total_us.get(key, 0) + max(0, stop - start)
        self._dot_open.clear()
        if self._song_open is not None:
            code, start = self._song_open
            stop = min(end, self.song_ends_us) if self.song_ends_us else end
            self._song_total_us[code] = self._song_total_us.get(code, 0) + max(0, stop - start)
            self._song_open = None

    def _build_result(self, engine_state: Dict[str, Any]) -> FightResult:
        """Aggregate the fight into a :class:`FightResult`."""
        self._close_open_intervals()
        duration = self.end_us / float(US)
        total_damage = 0.0
        damage_by_action: Dict[str, float] = {}
        total_potency = 0
        crit_events = 0
        dh_events = 0
        for record in self.damage_events:
            total_damage += record.amount
            total_potency += record.potency
            damage_by_action[record.key] = damage_by_action.get(record.key, 0.0) + record.amount
            if record.crit:
                crit_events += 1
            if record.direct_hit:
                dh_events += 1
        damage_event_count = len(self.damage_events)

        action_counts: Dict[str, int] = {}
        gcd_count = 0
        ogcd_count = 0
        for cast in self.casts:
            action_counts[cast.key] = action_counts.get(cast.key, 0) + 1
            if cast.is_gcd:
                gcd_count += 1
            else:
                ogcd_count += 1

        rolling_us = 0
        clipped_us = 0
        casts = self._gcd_casts
        for index, (start, recast_us) in enumerate(casts):
            nxt = casts[index + 1][0] if index + 1 < len(casts) else self.end_us
            gap = max(0, nxt - start)
            rolling_us += min(recast_us, gap)
            if index + 1 < len(casts) and gap > recast_us:
                clipped_us += gap - recast_us

        dot_uptime = {
            key: self._dot_total_us.get(key, 0) / float(self.end_us)
            for key in sorted(self._dot_total_us)
        }
        song_seconds = {
            code: self._song_total_us.get(code, 0) / float(US) for code in SONG_ORDER
        }

        if not self.casts:
            raise SimulationError("the fight produced zero casts")
        if self._pulses and len(self.rejections) > MAX_REJECTION_FRACTION * self._pulses:
            raise SimulationError(
                f"{len(self.rejections)} core rejections over {self._pulses} pulses exceeds "
                f"{MAX_REJECTION_FRACTION:.0%}"
            )

        return FightResult(
            config=self.config,
            duration_s=duration,
            total_damage=total_damage,
            dps=total_damage / duration if duration else 0.0,
            total_potency=total_potency,
            potency_per_second=total_potency / duration if duration else 0.0,
            gcd_count=gcd_count,
            ogcd_count=ogcd_count,
            gcd_uptime=rolling_us / float(self.end_us) if self.end_us else 0.0,
            clipped_s=clipped_us / float(US),
            action_counts={k: action_counts[k] for k in sorted(action_counts)},
            damage_by_action={k: damage_by_action[k] for k in sorted(damage_by_action)},
            dot_uptime=dot_uptime,
            song_seconds=song_seconds,
            song_casts={code: self._song_casts.get(code, 0) for code in SONG_ORDER},
            wasted=dict(self.wasted_procs),
            casts=tuple(self.casts),
            damage=tuple(self.damage_events),
            rejections=tuple(self.rejections),
            client_rejections=tuple(self._client_rejections),
            warnings=tuple(self._warnings),
            engine_state=engine_state,
            crit_rate=(crit_events / damage_event_count) if damage_event_count else 0.0,
            dh_rate=(dh_events / damage_event_count) if damage_event_count else 0.0,
            damage_event_count=damage_event_count,
        )

    def _potency_for(self, key: str, data: ActionData) -> int:
        """The potency one cast of `key` is worth right now."""
        if key == KEY_APEX:
            return int(apex_potency(self.soul_voice, self.job))
        if key == KEY_PITCH_PERFECT:
            stacks = max(1, min(self.repertoire, self._pp_max))
            return int(self._pp_potency[stacks - 1])
        if key == KEY_ENCORE:
            instance = self.player_statuses.get(KEY_ENCORE_READY)
            codas = instance.codas if instance is not None else self.coda_count_for_finale
            codas = max(0, min(codas, len(self._encore_potency) - 1))
            return int(self._encore_potency[codas])
        return int(data.potency)

    @property
    def trace_lines(self) -> Tuple[str, ...]:
        """One line per cast when `FightConfig.trace` is set."""
        return tuple(self._trace_lines)


def run_fight(config: FightConfig, tables: Optional[Tables] = None) -> FightResult:
    """Convenience wrapper around `Simulation(config).run()`."""
    return Simulation(config, tables).run()
