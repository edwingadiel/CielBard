"""Machinist training-dummy simulator that drives the shipped CielMachinist engine.

`CielMachinist/CielMachinist_Data.lua` and `CielMachinist_Rotation.lua` are loaded
verbatim into a `lupa` runtime next to `sim_mch/fakeclient.lua`, which imitates the
MMOMinion client and enforces the game's rules. The Lua side produces a cast log; this
module prices it.

Machinist has no random procs, so the rotation is a pure function of the configuration.
`simulate` therefore reports *expected* damage (critical and direct hits at their mean),
which makes two configurations directly comparable from one run each. `rolled_dps` draws
actual critical/direct hits and variance for anyone who wants a distribution.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(__file__).resolve().parent / "data"
MODULE_DIR = ROOT / "CielMachinist"

__all__ = ["FightConfig", "BuffWindow", "FightResult", "load_tables", "build_runtime", "simulate"]


@dataclass(frozen=True)
class BuffWindow:
    """A recurring party damage buff: `mult` for `duration_s`, first at `offset_s`, every `every_s`."""

    every_s: float = 120.0
    offset_s: float = 6.0
    duration_s: float = 20.0
    mult: float = 1.10

    def active(self, t: float) -> bool:
        if t < self.offset_s:
            return False
        return (t - self.offset_s) % self.every_s < self.duration_s


@dataclass
class FightConfig:
    """One simulated fight. `engine` holds dotted CielMachinistData.Defaults overrides."""

    seconds: float = 360.0
    kill_time_s: Optional[float] = None
    enemies: int = 1
    gcd_s: Optional[float] = None
    pulse_ms: int = 30
    ping_ms: float = 0.0
    jitter_ms: float = 0.0
    seed: int = 1
    potions: int = 0
    start_in_combat: bool = True
    pull_after_s: Optional[float] = None
    arm_prepull_at_s: Optional[float] = None
    party_buffs: Tuple[BuffWindow, ...] = ()
    engine: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FightResult:
    """Priced outcome of one fight. Times are seconds from the pull."""

    duration_s: float
    dps: float
    potency_per_s: float
    damage_by_action: Dict[str, float]
    casts: Dict[str, int]
    wildfire_hits: List[int]
    queens: List[Tuple[float, int]]
    stats: Dict[str, float]
    hits: List[Dict[str, Any]]
    log: List[Dict[str, Any]]

    def to_dict(self, include_log: bool = False) -> Dict[str, Any]:
        out = {
            "duration_s": round(self.duration_s, 3),
            "dps": round(self.dps, 3),
            "potency_per_s": round(self.potency_per_s, 4),
            "damage_by_action": {k: round(v, 1) for k, v in sorted(self.damage_by_action.items())},
            "casts": dict(sorted(self.casts.items())),
            "wildfire_hits": self.wildfire_hits,
            "queens": [[round(t, 2), b] for t, b in self.queens],
            "stats": {k: round(v, 3) for k, v in sorted(self.stats.items())},
        }
        if include_log:
            out["log"] = self.log
        return out


def load_tables() -> Dict[str, Dict[str, Any]]:
    """The four JSON tables, with `_notes`-style keys removed."""
    tables = {}
    for name in ("actions", "statuses", "job", "stats"):
        raw = json.loads((DATA_DIR / f"{name}.json").read_text(encoding="utf-8"))
        tables[name] = {k: v for k, v in raw.items() if not k.startswith("_")}
    return tables


def _to_lua(lua: LuaRuntime, value: Any) -> Any:
    if isinstance(value, Mapping):
        table = lua.table()
        for key, child in value.items():
            if isinstance(key, str) and key.startswith("_"):
                continue
            table[key] = _to_lua(lua, child)
        return table
    if isinstance(value, (list, tuple)):
        table = lua.table()
        for index, child in enumerate(value, start=1):
            table[index] = _to_lua(lua, child)
        return table
    return value


_INIT_ENGINE = """
local overrides = ...
local function clone(v)
    if type(v) ~= "table" then return v end
    local r = {}
    for k, c in pairs(v) do r[k] = clone(c) end
    return r
end
local config = clone(CielMachinistData.Defaults)
for path, value in pairs(overrides) do
    local node, parts = config, {}
    for part in string.gmatch(path, "[^%.]+") do parts[#parts + 1] = part end
    for i = 1, #parts - 1 do
        if type(node[parts[i]]) ~= "table" then node[parts[i]] = {} end
        node = node[parts[i]]
    end
    if node[parts[#parts]] == nil and parts[1] ~= "abilities" and parts[1] ~= "aoeTargets" then
        error("unknown engine setting: " .. path)
    end
    node[parts[#parts]] = value
end
CielMachinistEngine.Init(config)
return config
"""


def build_runtime(config: FightConfig, tables: Optional[Dict[str, Dict[str, Any]]] = None) -> LuaRuntime:
    """A Lua state with the shipped engine, the fake client and `config` applied."""
    tables = tables or load_tables()
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute((MODULE_DIR / "CielMachinist_Data.lua").read_text(encoding="utf-8"))
    g = lua.globals()
    g.SIM_ACTIONS = _to_lua(lua, tables["actions"])
    g.SIM_STATUSES = _to_lua(lua, tables["statuses"])
    g.SIM_JOB = _to_lua(lua, tables["job"])
    g.SIM_CFG = _to_lua(lua, {
        "seed": config.seed, "pulse_ms": config.pulse_ms, "ping_ms": config.ping_ms,
        "jitter_ms": config.jitter_ms, "enemies": config.enemies, "potions": config.potions,
        "start_in_combat": config.start_in_combat,
        **({"gcd_s": config.gcd_s} if config.gcd_s else {}),
        **({"kill_time_s": config.kill_time_s} if config.kill_time_s else {}),
        **({"pull_after_s": config.pull_after_s} if config.pull_after_s is not None else {}),
    })
    lua.execute((Path(__file__).resolve().parent / "fakeclient.lua").read_text(encoding="utf-8"))
    lua.execute((MODULE_DIR / "CielMachinist_Rotation.lua").read_text(encoding="utf-8"))
    overrides = dict(config.engine)
    if config.potions > 0:
        overrides.setdefault("usePotion", True)
    lua.eval("function(src, overrides) return load(src)(overrides) end")(_INIT_ENGINE, _to_lua(lua, overrides))
    return lua


def _aoe_multiplier(aoe: Any, enemies: int) -> float:
    if enemies <= 1 or aoe in (None, "single"):
        return 1.0
    if aoe == "all":
        return float(enemies)
    return 1.0 + (enemies - 1) * (1.0 - float(aoe))


def _price(config: FightConfig, tables: Dict[str, Dict[str, Any]], log: List[Dict[str, Any]],
           wildfires: List[Dict[str, Any]], queens: List[Dict[str, Any]], overdrives: List[float],
           potions: List[float], pull_at: float, duration: float) -> List[Dict[str, Any]]:
    """Turn the cast log into damage events (times relative to the pull)."""
    actions, job, stats = tables["actions"], tables["job"], tables["stats"]
    crit = 1.0 + stats["crit_rate"] * (stats["crit_mult"] - 1.0)
    dh = 1.0 + stats["dh_rate"] * (stats["dh_mult"] - 1.0)
    expected = crit * dh
    guaranteed = stats["crit_mult"] * stats["dh_mult"]
    medicated = float(job["potion"]["duration_s"])
    potion_mult = float(stats.get("potion_damage_mult", 1.0))

    def buffs(t: float) -> float:
        mult = 1.0
        for window in config.party_buffs:
            if window.active(t):
                mult *= window.mult
        if any(p <= t < p + medicated for p in potions):
            mult *= potion_mult
        return mult

    hits: List[Dict[str, Any]] = []

    def add(t: float, name: str, potency: float, crit_mode: str, snapshot_t: Optional[float] = None) -> None:
        if t < 0 or t > duration or potency <= 0:
            return
        factor = {"expected": expected, "guaranteed": guaranteed, "none": 1.0}[crit_mode]
        hits.append({"t": t, "name": name, "potency": potency, "crit_mode": crit_mode,
                     "mult": buffs(t if snapshot_t is None else snapshot_t), "factor": factor})

    for entry in log:
        key, t = entry["name"], entry["t"] - pull_at
        data = actions.get(key)
        if not data or "potency" not in data:
            continue
        potency = float(data["potency"])
        if data.get("combo_potency") and entry.get("combo"):
            potency = float(data["combo_potency"])
        if data.get("gcd") and data.get("aoe") == "single" and entry.get("overheated"):
            potency += float(job["overheated_single_target_bonus"])
        potency *= _aoe_multiplier(data.get("aoe"), int(entry.get("enemies", 1)))
        sure = data.get("guaranteed_crit_dh") or entry.get("reassembled")
        add(t, key, potency, "guaranteed" if sure else "expected")
        dot = data.get("dot")
        if dot:
            ticks = int(dot["duration_s"] // job["dot_tick_s"])
            for n in range(1, ticks + 1):
                add(t + n * job["dot_tick_s"], key + " (DoT)",
                    float(dot["potency"]) * int(entry.get("enemies", 1)), "expected", snapshot_t=t)

    wf = job["wildfire"]
    for fire in wildfires:
        start = fire["t"] - pull_at
        add(start + tables["statuses"]["WildfireSelf"]["duration_s"], "Wildfire",
            wf["potency_per_hit"] * fire["hits"], "expected" if wf.get("can_crit") else "none", snapshot_t=start)

    queen = job["queen"]
    for summon in queens:
        start = summon["t"] - pull_at
        cut = min((o - pull_at for o in overdrives if start <= o - pull_at <= start + 20), default=None)
        finishers = list(queen["overdrive_finisher_offsets_s"])
        for hit in queen["hits"]:
            potency = hit["per_battery"] * summon["battery"] * queen["potency_scale"]
            when = start + hit["offset_s"]
            if cut is not None and when > cut:
                if not hit.get("finisher"):
                    continue
                when = cut + finishers.pop(0)
            add(when, "Queen: " + hit["name"], potency, "expected")
    hits.sort(key=lambda h: (h["t"], h["name"]))
    return hits


def simulate(config: FightConfig, tables: Optional[Dict[str, Dict[str, Any]]] = None) -> FightResult:
    """Run one fight and price it at expected critical/direct-hit rates."""
    tables = tables or load_tables()
    lua = build_runtime(config, tables)
    if config.arm_prepull_at_s is not None:
        lua.execute("local at = ...; while clock - CLOCK0 < at * 1000 do CielMachinistEngine.Step(true) advance(%d) end"
                    % config.pulse_ms, config.arm_prepull_at_s)
        lua.execute("armPrepull(10)")
    lua.globals().run(config.seconds)

    sim = lua.globals().sim
    pull_at = (sim.pullAt or 0) / 1000.0
    duration = float(sim.foughtFor)
    log = [dict(entry.items()) for entry in sim.log.values()]
    wildfires = [dict(w.items()) for w in sim.wildfires.values()]
    queens = [dict(q.items()) for q in sim.queens.values()]
    overdrives = [o.t for o in sim.overdrives.values()]
    potions = [p.t - pull_at for p in sim.potionsUsed.values()]

    hits = _price(config, tables, log, wildfires, queens, overdrives, potions, pull_at, duration)
    scalar = float(tables["stats"]["potency_to_damage"])
    by_action: Dict[str, float] = {}
    total = 0.0
    for hit in hits:
        damage = hit["potency"] * hit["factor"] * hit["mult"] * scalar
        hit["damage"] = damage
        total += damage
        by_action[hit["name"]] = by_action.get(hit["name"], 0.0) + damage
    casts: Dict[str, int] = {}
    for entry in log:
        casts[entry["name"]] = casts.get(entry["name"], 0) + 1
    for entry in log:
        entry["t"] = round(entry["t"] - pull_at, 3)

    stats = {
        "gcd_idle_s": sim.idle.gcd, "drill_capped_s": sim.idle.drillCapped,
        "air_anchor_idle_s": sim.idle.AirAnchor, "chain_saw_idle_s": sim.idle.ChainSaw,
        "double_check_capped_s": sim.capped.DoubleCheck, "checkmate_capped_s": sim.capped.Checkmate,
        "reassemble_capped_s": sim.capped.Reassemble, "heat_wasted": sim.wasted.heat,
        "battery_wasted": sim.wasted.battery, "broken_combos": sim.brokenCombos,
        "heat_left": sim.heat, "battery_left": sim.battery,
    }
    safe = max(duration, 1e-9)
    return FightResult(
        duration_s=duration, dps=total / safe,
        potency_per_s=sum(h["potency"] * h["factor"] * h["mult"] for h in hits) / safe,
        damage_by_action=by_action, casts=casts,
        wildfire_hits=[int(w["hits"]) for w in wildfires],
        queens=[(q["t"] - pull_at, int(q["battery"])) for q in queens],
        stats={k: float(v) for k, v in stats.items()}, hits=hits, log=log,
    )


def rolled_dps(result: FightResult, tables: Dict[str, Dict[str, Any]], seed: int) -> float:
    """DPS of the same fight with critical hits, direct hits and variance actually rolled."""
    stats = tables["stats"]
    rng = random.Random(seed)
    total = 0.0
    for hit in result.hits:
        factor = 1.0
        if hit["crit_mode"] == "guaranteed":
            factor = stats["crit_mult"] * stats["dh_mult"]
        elif hit["crit_mode"] == "expected":
            if rng.random() < stats["crit_rate"]:
                factor *= stats["crit_mult"]
            if rng.random() < stats["dh_rate"]:
                factor *= stats["dh_mult"]
        spread = stats.get("damage_variance", 0.0)
        total += hit["potency"] * factor * hit["mult"] * (1 + rng.uniform(-spread, spread))
    return total * float(stats["potency_to_damage"]) / max(result.duration_s, 1e-9)


def standard_party_buffs(mult: float = 1.10) -> Tuple[BuffWindow, ...]:
    """One 20 s window every two minutes starting six seconds into the pull."""
    return (BuffWindow(every_s=120.0, offset_s=6.0, duration_s=20.0, mult=mult),)


def parse_value(text: str) -> Any:
    lowered = text.strip().lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    try:
        return int(text)
    except ValueError:
        try:
            return float(text)
        except ValueError:
            return text


def config_fields() -> Sequence[str]:
    return tuple(FightConfig.__dataclass_fields__)
