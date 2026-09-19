"""Dancer simulator that drives the shipped CielDancer engine.

`CielDancer/CielDancer_Data.lua` and `CielDancer_Rotation.lua` are loaded verbatim into a
`lupa` runtime next to `sim_dnc/fakeclient.lua`, which imitates the MMOMinion client and
enforces the game's rules. The Lua side produces a cast log that records the buffs up at
each cast; this module prices it at expected critical / direct-hit rates.

Dancer is random (step sequences, 50% procs, Esprit from allies), so a fight is a function
of (configuration, seed) and comparisons need several seeds. `simulate_many` averages.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from lupa import LuaRuntime

from sim_mch.core import BuffWindow, _to_lua, parse_value, standard_party_buffs  # noqa: F401  (re-exported)

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(__file__).resolve().parent / "data"
MODULE_DIR = ROOT / "CielDancer"

__all__ = ["FightConfig", "FightResult", "BuffWindow", "load_tables", "build_runtime", "simulate",
           "simulate_many", "standard_party_buffs", "parse_value"]


@dataclass
class FightConfig:
    """One simulated fight. `engine` holds dotted CielDancerData.Defaults overrides."""

    seconds: float = 360.0
    kill_time_s: Optional[float] = None
    enemies: int = 1
    gcd_s: Optional[float] = None
    pulse_ms: int = 30
    ping_ms: float = 0.0
    seed: int = 1
    potions: int = 0
    start_in_combat: bool = True
    pull_after_s: Optional[float] = None
    arm_prepull_at_s: Optional[float] = None
    partner: bool = True
    party_size: int = 8
    ally_esprit_chance: Optional[float] = None
    target_distance: float = 3.0
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
    stats: Dict[str, float]
    hits: List[Dict[str, Any]]
    log: List[Dict[str, Any]]

    def to_dict(self, include_log: bool = False) -> Dict[str, Any]:
        out = {
            "duration_s": round(self.duration_s, 3), "dps": round(self.dps, 3),
            "potency_per_s": round(self.potency_per_s, 4),
            "damage_by_action": {k: round(v, 1) for k, v in sorted(self.damage_by_action.items())},
            "casts": dict(sorted(self.casts.items())),
            "stats": {k: round(v, 3) for k, v in sorted(self.stats.items())},
        }
        if include_log:
            out["log"] = self.log
        return out


def load_tables() -> Dict[str, Dict[str, Any]]:
    tables = {}
    for name in ("actions", "statuses", "job", "stats"):
        raw = json.loads((DATA_DIR / f"{name}.json").read_text(encoding="utf-8"))
        tables[name] = {k: v for k, v in raw.items() if not k.startswith("_")}
    return tables


_INIT_ENGINE = """
local overrides = ...
local function clone(v)
    if type(v) ~= "table" then return v end
    local r = {}
    for k, c in pairs(v) do r[k] = clone(c) end
    return r
end
local config = clone(CielDancerData.Defaults)
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
CielDancerEngine.Init(config)
return config
"""


def build_runtime(config: FightConfig, tables: Optional[Dict[str, Dict[str, Any]]] = None) -> LuaRuntime:
    """A Lua state with the shipped engine, the fake client and `config` applied."""
    tables = tables or load_tables()
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute((MODULE_DIR / "CielDancer_Data.lua").read_text(encoding="utf-8"))
    g = lua.globals()
    g.SIM_ACTIONS = _to_lua(lua, tables["actions"])
    g.SIM_STATUSES = _to_lua(lua, tables["statuses"])
    g.SIM_JOB = _to_lua(lua, tables["job"])
    cfg = {"seed": config.seed, "pulse_ms": config.pulse_ms, "ping_ms": config.ping_ms,
           "enemies": config.enemies, "potions": config.potions, "start_in_combat": config.start_in_combat,
           "partner": config.partner, "party_size": config.party_size, "target_distance": config.target_distance}
    for key in ("gcd_s", "kill_time_s", "pull_after_s", "ally_esprit_chance"):
        if getattr(config, key) is not None:
            cfg[key] = getattr(config, key)
    g.SIM_CFG = _to_lua(lua, cfg)
    lua.execute((Path(__file__).resolve().parent / "fakeclient.lua").read_text(encoding="utf-8"))
    lua.execute((MODULE_DIR / "CielDancer_Rotation.lua").read_text(encoding="utf-8"))
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
           pull_at: float, duration: float) -> List[Dict[str, Any]]:
    actions, job, stats = tables["actions"], tables["job"], tables["stats"]
    potion_mult = float(stats.get("potion_damage_mult", 1.0))
    hits: List[Dict[str, Any]] = []
    for entry in log:
        data = actions.get(entry["name"])
        t = entry["t"] - pull_at
        if not data or "potency" not in data or t < -0.001 or t > duration or entry.get("wrong"):
            continue
        potency = float(data["potency"])
        if data.get("combo_potency") and entry.get("combo"):
            potency = float(data["combo_potency"])
        potency *= _aoe_multiplier(data.get("aoe"), int(entry.get("enemies", 1)))
        crit, dh = stats["crit_rate"], stats["dh_rate"]
        if entry.get("devilment"):
            crit += job["devilment"]["crit_rate_bonus"]
            dh += job["devilment"]["dh_rate_bonus"]
        if data.get("guaranteed_crit_dh"):
            factor = stats["crit_mult"] * stats["dh_mult"]
        else:
            factor = (1 + min(crit, 1.0) * (stats["crit_mult"] - 1)) * (1 + min(dh, 1.0) * (stats["dh_mult"] - 1))
        mult = float(entry.get("standard", 1.0)) * float(entry.get("technical", 1.0))
        if entry.get("medicated"):
            mult *= potion_mult
        for window in config.party_buffs:
            if window.active(t):
                mult *= window.mult
        hits.append({"t": t, "name": entry["name"], "potency": potency, "factor": factor, "mult": mult})
    return hits


def simulate(config: FightConfig, tables: Optional[Dict[str, Dict[str, Any]]] = None) -> FightResult:
    """Run one fight and price it at expected critical / direct-hit rates."""
    tables = tables or load_tables()
    lua = build_runtime(config, tables)
    if config.arm_prepull_at_s is not None:
        lua.execute("local at = ...; while clock - CLOCK0 < at * 1000 do CielDancerEngine.Step(true) advance(%d) end"
                    % config.pulse_ms, config.arm_prepull_at_s)
        lua.execute("armPrepull(14)")
    lua.globals().run(config.seconds)

    sim = lua.globals().sim
    pull_at = (sim.pullAt or 0) / 1000.0
    duration = float(sim.foughtFor)
    log = [dict(entry.items()) for entry in sim.log.values()]
    hits = _price(config, tables, log, pull_at, duration)
    scalar = float(tables["stats"]["potency_to_damage"])
    by_action: Dict[str, float] = {}
    total = 0.0
    for hit in hits:
        hit["damage"] = hit["potency"] * hit["factor"] * hit["mult"] * scalar
        total += hit["damage"]
        by_action[hit["name"]] = by_action.get(hit["name"], 0.0) + hit["damage"]
    casts: Dict[str, int] = {}
    for entry in log:
        entry["t"] = round(entry["t"] - pull_at, 3)
        casts[entry["name"]] = casts.get(entry["name"], 0) + 1

    stats: Dict[str, float] = {
        "gcd_idle_s": sim.idle.gcd, "standard_step_idle_s": sim.idle.StandardStep,
        "technical_step_idle_s": sim.idle.TechnicalStep, "flourish_idle_s": sim.idle.Flourish,
        "devilment_idle_s": sim.idle.Devilment, "esprit_wasted": sim.wasted.esprit,
        "feathers_wasted": sim.wasted.feathers, "wrong_steps": sim.wrongSteps,
        "broken_combos": sim.brokenCombos, "esprit_left": sim.esprit, "feathers_left": sim.feathers,
    }
    for key, count in sim.lapsed.items():
        stats[f"lapsed_{key}"] = count
    for key, count in sim.overwritten.items():
        stats[f"overwritten_{key}"] = count
    safe = max(duration, 1e-9)
    return FightResult(duration_s=duration, dps=total / safe,
                       potency_per_s=sum(h["potency"] * h["factor"] * h["mult"] for h in hits) / safe,
                       damage_by_action=by_action, casts=casts,
                       stats={k: float(v) for k, v in stats.items()}, hits=hits, log=log)


def simulate_many(config: FightConfig, seeds: Iterable[int],
                  tables: Optional[Dict[str, Dict[str, Any]]] = None) -> List[FightResult]:
    tables = tables or load_tables()
    return [simulate(replace(config, seed=seed), tables) for seed in seeds]


def config_fields() -> Tuple[str, ...]:
    return tuple(FightConfig.__dataclass_fields__)
