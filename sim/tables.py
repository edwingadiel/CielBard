"""Game data tables for the CielBard simulator.

Every potency, duration, recast, proc rate, buff percentage and status id the simulator
knows lives in `sim/data/*.json`. This module loads those files, validates them, and
exposes them as frozen dataclasses. An expansion patch is a table edit, never a code edit.

The module also owns the two derived curves that are pure functions of the tables:
`apex_potency` (Apex Arrow's gauge-scaled potency) and `gcd_recast` (haste rounding).
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

__all__ = [
    "SimDataError",
    "Grant",
    "ActionData",
    "StatusData",
    "Tables",
    "apex_potency",
    "gcd_recast",
]

ACTION_KINDS = frozenset({"gcd", "ogcd", "song", "buff", "item"})

_ACTION_KEYS = frozenset(
    {
        "id",
        "name",
        "kind",
        "potency",
        "recast_s",
        "cooldown_s",
        "max_charges",
        "self_target",
        "aoe",
        "falloff",
        "multi_hit_eligible",
        "grants",
        "requires",
        "status_gained_id",
        "notes",
    }
)
_GRANT_KEYS = frozenset({"status", "chance", "duration_s"})
_STATUS_KEYS = frozenset(
    {
        "id",
        "name",
        "duration_s",
        "on_target",
        "dot_potency",
        "snapshots",
        "max_stacks",
        "weaponskill_hits",
        "damage_mult",
        "crit_add",
        "dh_add",
        "notes",
    }
)

_REQUIRED_JOB_KEYS = (
    "gcd_base_s",
    "gcd_rounding_ms",
    "anim_lock_gcd_s",
    "anim_lock_ogcd_s",
    "server_tick_s",
    "repertoire_proc_chance",
    "repertoire_on_song_timer",
    # `repertoire_independent_of_dots` is deliberately absent: either it or the
    # superseded `repertoire_requires_dot` must be present, which `_validate_job`
    # checks, so a legacy job.json still loads and the back-compat path in
    # `sim.core` is reachable.
    "repertoire_skip_final_tick",
    "soul_voice_per_repertoire",
    "soul_voice_max",
    "pitch_perfect_max_stacks",
    "pitch_perfect_potency",
    "army_paeon_max_stacks",
    "army_paeon_haste_per_stack_pct",
    "army_muse_haste_by_stacks_pct",
    "army_ethos_s",
    "ballad_charge_reduction_s",
    "song_duration_s",
    "coda_damage_mult",
    "radiant_encore_potency",
    "apex",
    "hawks_eye_proc_chance",
    "auto_attack_interval_s",
    "gcd_queue_window_s",
)

_REQUIRED_APEX_KEYS = (
    "gauge_min",
    "gauge_max",
    "potency_min",
    "potency_max",
    "blast_gauge_threshold",
)

_REQUIRED_STAT_KEYS = (
    "crit_rate",
    "crit_mult",
    "dh_rate",
    "dh_mult",
    "crit_dh_independent",
    "potency_to_damage",
    "auto_attack_dps",
    "damage_variance",
    "potion_damage_mult",
)


class SimDataError(ValueError):
    """Raised when a data file is missing, malformed, or inconsistent with the Lua."""


@dataclass(frozen=True)
class Grant:
    """One status application performed by an action on execution."""

    status: str
    chance: float = 1.0
    duration_s: float | None = None  # None -> the status's own duration


@dataclass(frozen=True)
class ActionData:
    """The static, data-driven description of one Bard action."""

    key: str
    id: int
    name: str
    kind: str  # "gcd" | "ogcd" | "song" | "buff" | "item"
    potency: int
    recast_s: float
    cooldown_s: float
    max_charges: int
    self_target: bool
    aoe: bool
    falloff: float
    grants: tuple[Grant, ...]
    requires: tuple[str, ...]
    status_gained_id: int
    notes: str
    multi_hit_eligible: bool = False
    """True when a multi-hit status (Barrage) can multiply this weaponskill's hits."""

    @property
    def is_gcd(self) -> bool:
        """True when the action rolls the global cooldown."""
        return self.kind == "gcd"


@dataclass(frozen=True)
class StatusData:
    """The static, data-driven description of one buff, debuff or damage-over-time."""

    key: str
    id: int
    name: str
    duration_s: float
    on_target: bool
    dot_potency: int
    snapshots: bool
    max_stacks: int
    weaponskill_hits: int = 1
    damage_mult: float = 1.0
    crit_add: float = 0.0
    dh_add: float = 0.0
    notes: str = ""

    @property
    def is_dot(self) -> bool:
        """True when the status deals damage on the server tick."""
        return self.dot_potency > 0


def apex_potency(gauge: float, job: Mapping[str, Any]) -> int:
    """Apex Arrow potency for a Soul Voice `gauge`, using `job["apex"]`.

    Linear between (gauge_min, potency_min) and (gauge_max, potency_max), rounded half up
    and clamped to [potency_min, potency_max]. Only the 600-at-100 endpoint is documented
    in the brief; the 100-at-20 floor is the simulator's assumption (see calibration.md).
    """
    apex = job["apex"]
    g_min = float(apex["gauge_min"])
    g_max = float(apex["gauge_max"])
    p_min = float(apex["potency_min"])
    p_max = float(apex["potency_max"])
    if g_max <= g_min:
        raise SimDataError("job.apex: gauge_max must be greater than gauge_min")
    clamped = min(max(float(gauge), g_min), g_max)
    raw = p_min + (clamped - g_min) * (p_max - p_min) / (g_max - g_min)
    return int(math.floor(raw + 0.5))


def gcd_recast(base_s: float, haste_pct: float, rounding_ms: int = 10) -> float:
    """The GCD recast under `haste_pct` percent haste, truncated to `rounding_ms`.

    `recast = round_down_to(base_s * (100 - haste_pct) / 100, rounding_ms)`. The
    arithmetic is done in milliseconds with a 1e-9 tolerance so that an exact value such
    as 2.100 does not truncate to 2.090 through binary floating point.
    """
    if rounding_ms <= 0:
        raise SimDataError("gcd_rounding_ms must be positive")
    raw_ms = float(base_s) * 1000.0 * (100.0 - float(haste_pct)) / 100.0
    if raw_ms < 0.0:
        raw_ms = 0.0
    steps = math.floor(raw_ms / rounding_ms + 1e-9)
    return (steps * rounding_ms) / 1000.0


def _read_json(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise SimDataError(f"missing data file: {path}") from exc
    except OSError as exc:  # pragma: no cover - unusual filesystem failure
        raise SimDataError(f"cannot read data file {path}: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SimDataError(f"malformed JSON in {path}: {exc}") from exc


def _require_mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise SimDataError(f"{where}: expected a JSON object, got {type(value).__name__}")
    return value


def _number(record: Mapping[str, Any], key: str, where: str, default: float) -> float:
    value = record.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SimDataError(f"{where}.{key}: expected a number, got {value!r}")
    return float(value)


def _integer(record: Mapping[str, Any], key: str, where: str, default: int) -> int:
    value = record.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise SimDataError(f"{where}.{key}: expected an integer, got {value!r}")
    return int(value)


def _boolean(record: Mapping[str, Any], key: str, where: str, default: bool) -> bool:
    value = record.get(key, default)
    if not isinstance(value, bool):
        raise SimDataError(f"{where}.{key}: expected true or false, got {value!r}")
    return value


def _text(record: Mapping[str, Any], key: str, where: str, default: str) -> str:
    value = record.get(key, default)
    if not isinstance(value, str):
        raise SimDataError(f"{where}.{key}: expected a string, got {value!r}")
    return value


def _parse_grants(raw: Any, where: str) -> tuple[Grant, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise SimDataError(f"{where}.grants: expected a list, got {type(raw).__name__}")
    grants: list[Grant] = []
    for index, entry in enumerate(raw):
        spot = f"{where}.grants[{index}]"
        record = _require_mapping(entry, spot)
        unknown = sorted(set(record) - _GRANT_KEYS)
        if unknown:
            raise SimDataError(f"{spot}: unknown key(s) {unknown}")
        status = record.get("status")
        if not isinstance(status, str) or not status:
            raise SimDataError(f"{spot}.status: expected a non-empty string")
        chance = _number(record, "chance", spot, 1.0)
        if not 0.0 <= chance <= 1.0:
            raise SimDataError(f"{spot}.chance: {chance} is outside [0, 1]")
        duration = record.get("duration_s")
        if duration is not None:
            duration = _number(record, "duration_s", spot, 0.0)
            if duration < 0.0:
                raise SimDataError(f"{spot}.duration_s: {duration} is negative")
        grants.append(Grant(status=status, chance=chance, duration_s=duration))
    return tuple(grants)


def _parse_requires(raw: Any, where: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise SimDataError(f"{where}.requires: expected a list, got {type(raw).__name__}")
    for entry in raw:
        if not isinstance(entry, str) or not entry:
            raise SimDataError(f"{where}.requires: expected status names, got {entry!r}")
    return tuple(raw)


def _parse_action(key: str, raw: Any) -> ActionData:
    where = f"actions.json[{key}]"
    record = _require_mapping(raw, where)
    unknown = sorted(set(record) - _ACTION_KEYS)
    if unknown:
        raise SimDataError(f"{where}: unknown key(s) {unknown}")
    for required in ("id", "name", "kind"):
        if required not in record:
            raise SimDataError(f"{where}: missing required key '{required}'")
    kind = record["kind"]
    if kind not in ACTION_KINDS:
        raise SimDataError(f"{where}.kind: {kind!r} is not one of {sorted(ACTION_KINDS)}")
    action_id = _integer(record, "id", where, 0)
    if action_id <= 0:
        raise SimDataError(f"{where}.id: {action_id} is not a positive action id")
    potency = _integer(record, "potency", where, 0)
    if potency < 0:
        raise SimDataError(f"{where}.potency: {potency} is negative")
    recast_s = _number(record, "recast_s", where, 0.0)
    if recast_s < 0.0:
        raise SimDataError(f"{where}.recast_s: {recast_s} is negative")
    cooldown_s = _number(record, "cooldown_s", where, 0.0)
    if cooldown_s < 0.0:
        raise SimDataError(f"{where}.cooldown_s: {cooldown_s} is negative")
    max_charges = _integer(record, "max_charges", where, 1)
    if max_charges < 1:
        raise SimDataError(f"{where}.max_charges: {max_charges} is below 1")
    falloff = _number(record, "falloff", where, 0.0)
    if not 0.0 <= falloff <= 1.0:
        raise SimDataError(f"{where}.falloff: {falloff} is outside [0, 1]")
    status_gained_id = _integer(record, "status_gained_id", where, 0)
    if status_gained_id < 0:
        raise SimDataError(f"{where}.status_gained_id: {status_gained_id} is negative")
    # Only the basic weaponskills are multiplied by Barrage; everything else neither
    # benefits from the status nor consumes it (see statuses.json, weaponskill_hits).
    multi_hit_eligible = _boolean(record, "multi_hit_eligible", where, False)
    if multi_hit_eligible and kind != "gcd":
        raise SimDataError(f"{where}.multi_hit_eligible: only a 'gcd' action may be eligible")
    return ActionData(
        key=key,
        id=action_id,
        name=_text(record, "name", where, key),
        kind=kind,
        potency=potency,
        recast_s=recast_s,
        cooldown_s=cooldown_s,
        max_charges=max_charges,
        self_target=_boolean(record, "self_target", where, False),
        aoe=_boolean(record, "aoe", where, False),
        falloff=falloff,
        grants=_parse_grants(record.get("grants"), where),
        requires=_parse_requires(record.get("requires"), where),
        status_gained_id=status_gained_id,
        notes=_text(record, "notes", where, ""),
        multi_hit_eligible=multi_hit_eligible,
    )


def _parse_status(key: str, raw: Any) -> StatusData:
    where = f"statuses.json[{key}]"
    record = _require_mapping(raw, where)
    unknown = sorted(set(record) - _STATUS_KEYS)
    if unknown:
        raise SimDataError(f"{where}: unknown key(s) {unknown}")
    for required in ("id", "name", "duration_s"):
        if required not in record:
            raise SimDataError(f"{where}: missing required key '{required}'")
    status_id = _integer(record, "id", where, 0)
    if status_id <= 0:
        raise SimDataError(f"{where}.id: {status_id} is not a positive status id")
    duration_s = _number(record, "duration_s", where, 0.0)
    if duration_s < 0.0:
        raise SimDataError(f"{where}.duration_s: {duration_s} is negative")
    dot_potency = _integer(record, "dot_potency", where, 0)
    if dot_potency < 0:
        raise SimDataError(f"{where}.dot_potency: {dot_potency} is negative")
    max_stacks = _integer(record, "max_stacks", where, 1)
    if max_stacks < 1:
        raise SimDataError(f"{where}.max_stacks: {max_stacks} is below 1")
    # Barrage's triple hit: the status makes the next damaging weaponskill land
    # `weaponskill_hits` times and is consumed by it. 1 means "no such effect".
    weaponskill_hits = _integer(record, "weaponskill_hits", where, 1)
    if weaponskill_hits < 1:
        raise SimDataError(f"{where}.weaponskill_hits: {weaponskill_hits} is below 1")
    damage_mult = _number(record, "damage_mult", where, 1.0)
    if damage_mult <= 0.0:
        raise SimDataError(f"{where}.damage_mult: {damage_mult} is not positive")
    return StatusData(
        key=key,
        id=status_id,
        name=_text(record, "name", where, key),
        duration_s=duration_s,
        on_target=_boolean(record, "on_target", where, False),
        dot_potency=dot_potency,
        snapshots=_boolean(record, "snapshots", where, False),
        max_stacks=max_stacks,
        weaponskill_hits=weaponskill_hits,
        damage_mult=damage_mult,
        crit_add=_number(record, "crit_add", where, 0.0),
        dh_add=_number(record, "dh_add", where, 0.0),
        notes=_text(record, "notes", where, ""),
    )


def _validate_job(job: Mapping[str, Any]) -> None:
    for key in _REQUIRED_JOB_KEYS:
        if key not in job:
            raise SimDataError(f"job.json: missing required key '{key}'")
    apex = job["apex"]
    if not isinstance(apex, dict):
        raise SimDataError("job.json.apex: expected a JSON object")
    for key in _REQUIRED_APEX_KEYS:
        if key not in apex:
            raise SimDataError(f"job.json.apex: missing required key '{key}'")
    if len(job["coda_damage_mult"]) != 4:
        raise SimDataError("job.json.coda_damage_mult: expected 4 entries (coda count 0..3)")
    if len(job["radiant_encore_potency"]) != 4:
        raise SimDataError(
            "job.json.radiant_encore_potency: expected 4 entries (coda count 0..3)"
        )
    if len(job["pitch_perfect_potency"]) != int(job["pitch_perfect_max_stacks"]):
        raise SimDataError(
            "job.json.pitch_perfect_potency: length must equal pitch_perfect_max_stacks"
        )
    if len(job["army_muse_haste_by_stacks_pct"]) != int(job["army_paeon_max_stacks"]):
        raise SimDataError(
            "job.json.army_muse_haste_by_stacks_pct: length must equal army_paeon_max_stacks"
        )
    for key in ("repertoire_proc_chance", "hawks_eye_proc_chance"):
        value = float(job[key])
        if not 0.0 <= value <= 1.0:
            raise SimDataError(f"job.json.{key}: {value} is outside [0, 1]")
    for key in ("repertoire_on_song_timer", "repertoire_skip_final_tick"):
        if not isinstance(job[key], bool):
            raise SimDataError(f"job.json.{key}: expected a JSON boolean")
    # MECHANICS_CORRECTIONS.md item 1 renamed `repertoire_requires_dot` to
    # `repertoire_independent_of_dots`; a table may carry either spelling, and
    # `sim.core` reads the old one as the inverse of the new one.
    dot_keys = [
        key for key in ("repertoire_independent_of_dots", "repertoire_requires_dot")
        if key in job
    ]
    if not dot_keys:
        raise SimDataError(
            "job.json: missing required key 'repertoire_independent_of_dots' "
            "(or the superseded 'repertoire_requires_dot')"
        )
    for key in dot_keys:
        if not isinstance(job[key], bool):
            raise SimDataError(f"job.json.{key}: expected a JSON boolean")
    for key in ("gcd_base_s", "server_tick_s", "song_duration_s", "auto_attack_interval_s"):
        if float(job[key]) <= 0.0:
            raise SimDataError(f"job.json.{key}: must be positive")
    if float(job["gcd_queue_window_s"]) < 0.0:
        raise SimDataError("job.json.gcd_queue_window_s: must be >= 0")
    if int(job["gcd_rounding_ms"]) <= 0:
        raise SimDataError("job.json.gcd_rounding_ms: must be positive")


def _validate_stats(stats: Mapping[str, Any]) -> None:
    for key in _REQUIRED_STAT_KEYS:
        if key not in stats:
            raise SimDataError(f"stats.json: missing required key '{key}'")
    for key in ("crit_rate", "dh_rate", "damage_variance"):
        value = float(stats[key])
        if not 0.0 <= value <= 1.0:
            raise SimDataError(f"stats.json.{key}: {value} is outside [0, 1]")
    for key in ("crit_mult", "dh_mult", "potency_to_damage", "potion_damage_mult"):
        if float(stats[key]) <= 0.0:
            raise SimDataError(f"stats.json.{key}: must be positive")
    if not isinstance(stats["crit_dh_independent"], bool):
        raise SimDataError("stats.json.crit_dh_independent: expected true or false")


@dataclass(frozen=True)
class Tables:
    """All game data, loaded once and shared read-only between fights."""

    actions: Mapping[str, ActionData]
    statuses: Mapping[str, StatusData]
    job: Mapping[str, Any]
    stats: Mapping[str, Any]
    data_dir: Path | None = None
    _actions_by_id: Mapping[int, ActionData] = field(
        default_factory=dict, repr=False, compare=False
    )
    _statuses_by_id: Mapping[int, StatusData] = field(
        default_factory=dict, repr=False, compare=False
    )

    @classmethod
    def load(cls, data_dir: Path | None = None) -> "Tables":
        """Load and validate the four JSON files (default: `sim/data`).

        Raises SimDataError on: a missing file, an unknown key in a record, a `grants`
        entry naming an unknown status, a `requires` entry naming an unknown status, a
        duplicate action id, or a negative duration/potency.
        """
        directory = Path(data_dir) if data_dir is not None else Path(__file__).resolve().parent / "data"

        raw_actions = _require_mapping(_read_json(directory / "actions.json"), "actions.json")
        raw_statuses = _require_mapping(_read_json(directory / "statuses.json"), "statuses.json")
        job = _require_mapping(_read_json(directory / "job.json"), "job.json")
        stats = _require_mapping(_read_json(directory / "stats.json"), "stats.json")

        statuses: dict[str, StatusData] = {}
        statuses_by_id: dict[int, StatusData] = {}
        for key in sorted(raw_statuses):
            status = _parse_status(key, raw_statuses[key])
            statuses[key] = status
            clash = statuses_by_id.get(status.id)
            if clash is not None:
                raise SimDataError(
                    f"statuses.json: duplicate status id {status.id} "
                    f"used by '{clash.key}' and '{key}'"
                )
            statuses_by_id[status.id] = status

        actions: dict[str, ActionData] = {}
        actions_by_id: dict[int, ActionData] = {}
        for key in sorted(raw_actions):
            action = _parse_action(key, raw_actions[key])
            for grant in action.grants:
                if grant.status not in statuses:
                    raise SimDataError(
                        f"actions.json[{key}].grants: unknown status '{grant.status}'"
                    )
            for requirement in action.requires:
                if requirement not in statuses:
                    raise SimDataError(
                        f"actions.json[{key}].requires: unknown status '{requirement}'"
                    )
            clash = actions_by_id.get(action.id)
            if clash is not None:
                raise SimDataError(
                    f"actions.json: duplicate action id {action.id} "
                    f"used by '{clash.key}' and '{key}'"
                )
            actions[key] = action
            actions_by_id[action.id] = action

        _validate_job(job)
        _validate_stats(stats)

        return cls(
            actions=actions,
            statuses=statuses,
            job=job,
            stats=stats,
            data_dir=directory,
            _actions_by_id=actions_by_id,
            _statuses_by_id=statuses_by_id,
        )

    def action(self, key: str) -> ActionData:
        """Look up by CielBard ability key. Raises KeyError with the key in the message."""
        try:
            return self.actions[key]
        except KeyError:
            raise KeyError(f"unknown action key: {key!r}") from None

    def by_id(self, action_id: int) -> ActionData | None:
        """Look up by FFXIV action id; None when the id is unknown (e.g. an item)."""
        return self._actions_by_id.get(int(action_id))

    def status(self, key: str) -> StatusData:
        """Look up a status by key. Raises KeyError with the key in the message."""
        try:
            return self.statuses[key]
        except KeyError:
            raise KeyError(f"unknown status key: {key!r}") from None

    def status_by_id(self, status_id: int) -> StatusData | None:
        """Look up a status by FFXIV status id; None when the id is unknown."""
        return self._statuses_by_id.get(int(status_id))

    def apex_potency(self, gauge: float) -> int:
        """Apex Arrow potency at `gauge` Soul Voice, using this table set's job data."""
        return apex_potency(gauge, self.job)

    def gcd_recast(self, haste_pct: float = 0.0) -> float:
        """The GCD recast under `haste_pct`, using this table set's job data."""
        return gcd_recast(
            float(self.job["gcd_base_s"]), haste_pct, int(self.job["gcd_rounding_ms"])
        )

    def verify_against_lua(self, repo_root: Path) -> list[str]:
        """Return human-readable discrepancies between actions.json/statuses.json and
        `CielBard/CielBard_Data.lua`. Empty list means the tables match the shipped ids.

        Implementation: regex `(\\w+)\\s*=\\s*(\\d+)` inside the `CielBardData.Actions`
        and `CielBardData.Statuses` blocks. Do not import the Lua runtime here -- this
        must work without lupa.

        Only records the simulator claims are real FFXIV actions are checked: `kind`
        `"item"` records (the potion placeholder) are addressed through GetItem, never by
        action id, and are absent from the Lua on purpose. Statuses present in the tables
        but absent from `CielBardData.Statuses` are simulator-internal by design (the
        engine compares `action.statusgainedid` against buff ids, never a literal), so
        only the Lua-to-table direction is checked for statuses.
        """
        lua_path = Path(repo_root) / "CielBard" / "CielBard_Data.lua"
        try:
            text = lua_path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise SimDataError(f"missing shipped Lua data file: {lua_path}") from exc

        lua_actions = _lua_id_block(text, "CielBardData.Actions", lua_path)
        lua_statuses = _lua_id_block(text, "CielBardData.Statuses", lua_path)

        problems: list[str] = []

        for key in sorted(lua_actions):
            lua_id = lua_actions[key]
            action = self.actions.get(key)
            if action is None:
                problems.append(
                    f"action '{key}' (id {lua_id}) is in CielBard_Data.lua "
                    f"but missing from actions.json"
                )
            elif action.id != lua_id:
                problems.append(
                    f"action '{key}': actions.json id {action.id} "
                    f"!= CielBard_Data.lua id {lua_id}"
                )

        for key in sorted(self.actions):
            action = self.actions[key]
            if action.kind == "item":
                continue
            if key not in lua_actions:
                problems.append(
                    f"action '{key}' (id {action.id}, kind {action.kind}) is in "
                    f"actions.json but missing from CielBard_Data.lua"
                )

        for key in sorted(lua_statuses):
            lua_id = lua_statuses[key]
            status = self.statuses.get(key)
            if status is None:
                problems.append(
                    f"status '{key}' (id {lua_id}) is in CielBard_Data.lua "
                    f"but missing from statuses.json"
                )
            elif status.id != lua_id:
                problems.append(
                    f"status '{key}': statuses.json id {status.id} "
                    f"!= CielBard_Data.lua id {lua_id}"
                )

        return problems


_ENTRY_RE = re.compile(r"(\w+)\s*=\s*(\d+)")


def _lua_id_block(text: str, table_name: str, path: Path) -> dict[str, int]:
    """Extract `name = id` pairs from one top-level CielBardData table."""
    marker = re.search(re.escape(table_name) + r"\s*=\s*\{", text)
    if marker is None:
        raise SimDataError(f"{path}: cannot find the {table_name} table")
    start = marker.end()
    depth = 1
    index = start
    while index < len(text) and depth > 0:
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        index += 1
    if depth != 0:
        raise SimDataError(f"{path}: unbalanced braces in {table_name}")
    body = text[start : index - 1]
    body = re.sub(r"--\[\[.*?\]\]", "", body, flags=re.S)
    body = re.sub(r"--[^\n]*", "", body)
    return {name: int(value) for name, value in _ENTRY_RE.findall(body)}
