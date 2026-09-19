"""Calibrate sim_mch against the parse summary produced by `mch-analysis/collect.py`.

    python -m sim_mch.calibrate --out sim_mch/output/calibration.md
    python -m sim_mch.calibrate --write        # also store the fitted values in sim_mch/data

Every parse is re-simulated at its own fight length (target dying at the end, potions as
the parse used them, the engine pulling). Three things come out:

1. `potency_to_damage`: sum(parse DPS without auto attacks) / sum(simulated potency per
   second). One scalar cannot fix a rotation-shape error, so it is reported next to...
2. ...the rotation comparison: casts per minute, Blazing Shots per Hypercharge, the opener,
   the Wildfire placement and the damage shares, engine against the top parses.
3. The Automaton Queen's measured hit timeline, which the simulator otherwise assumes.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .core import DATA_DIR, ROOT, FightConfig, FightResult, load_tables, simulate

DEFAULT_SUMMARY = ROOT / "mch-analysis" / "output" / "summary.json"

# simulator key -> FFLogs ability name
NAMES = {
    "HeatedSplitShot": "Heated Split Shot", "HeatedSlugShot": "Heated Slug Shot",
    "HeatedCleanShot": "Heated Clean Shot", "Drill": "Drill", "AirAnchor": "Air Anchor",
    "ChainSaw": "Chain Saw", "Excavator": "Excavator", "FullMetalField": "Full Metal Field",
    "BlazingShot": "Blazing Shot", "Hypercharge": "Hypercharge", "Wildfire": "Wildfire",
    "BarrelStabilizer": "Barrel Stabilizer", "Reassemble": "Reassemble", "DoubleCheck": "Double Check",
    "Checkmate": "Checkmate", "AutomatonQueen": "Automaton Queen", "QueenOverdrive": "Queen Overdrive",
}
QUEEN_COEFFICIENTS = {"Roller Dash": 4.8, "Arm Punch": 2.4, "Pile Bunker": 6.8, "Crowned Collider": 7.8}
FINISHERS = ("Pile Bunker", "Crowned Collider")


def simulate_parse(parse: Dict[str, Any], tables: Dict[str, Dict[str, Any]]) -> FightResult:
    seconds = float(parse["duration_s"])
    return simulate(FightConfig(seconds=seconds, kill_time_s=seconds, potions=int(parse.get("potions") or 0),
                                start_in_combat=False, engine={"requireCombat": False}), tables)


def parse_target_dps(parse: Dict[str, Any]) -> float:
    """The parse's DPS with auto attacks removed: the simulator does not model them."""
    return float(parse["amount"]) * (1.0 - float(parse.get("auto_attack_share") or 0.0))


def fit_scalar(parses: List[Dict[str, Any]], sims: List[FightResult]) -> float:
    return sum(parse_target_dps(p) for p in parses) / sum(s.potency_per_s for s in sims)


def queen_timeline(parses: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The modal hit sequence over all complete summons, with the median offset of each hit."""
    complete = [tuple(name for name, _ in tl) for p in parses for tl in p.get("queen_timelines", [])
                if tl and tl[-1][0] == FINISHERS[-1]]
    if not complete:
        return []
    modal = Counter(complete).most_common(1)[0][0]
    columns: List[List[float]] = [[] for _ in modal]
    for p in parses:
        for tl in p.get("queen_timelines", []):
            if tuple(name for name, _ in tl) == modal:
                for index, (_, dt) in enumerate(tl):
                    columns[index].append(dt)
    return [{"name": name, "per_battery": QUEEN_COEFFICIENTS[name],
             "offset_s": round(statistics.median(column), 2), **({"finisher": True} if name in FINISHERS else {})}
            for name, column in zip(modal, columns)]


def per_minute(casts: Dict[str, int], name: str, duration: float) -> float:
    return 60.0 * casts.get(name, 0) / duration


def mean(values) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def build_report(parses: List[Dict[str, Any]], sims: List[FightResult], scalar: float,
                 queen: List[Dict[str, Any]], tables: Dict[str, Dict[str, Any]]) -> str:
    top = parses[:10]
    lines = ["# sim_mch calibration", "",
             f"{len(parses)} parses, fight length {min(p['duration_s'] for p in parses):.0f}-"
             f"{max(p['duration_s'] for p in parses):.0f} s. Each was re-simulated at its own length with the "
             "shipped engine defaults, the target dying at the end, the parse's potion count, and the engine pulling.",
             "", "## 1. Damage scalar", ""]
    residuals = [100 * (s.potency_per_s * scalar / parse_target_dps(p) - 1) for p, s in zip(parses, sims)]
    auto = mean(p.get("auto_attack_share") or 0 for p in parses)
    lines += [f"- fitted `potency_to_damage` = **{scalar:.4f}** (was {tables['stats']['potency_to_damage']})",
              f"- auto attacks are {100 * auto:.2f}% of parse damage; they are removed from the target because "
              "the simulator does not model them (`auto_attack_share` in stats.json)",
              f"- residual: mean |error| {mean(abs(r) for r in residuals):.2f}%, worst {max(residuals, key=abs):+.2f}%",
              f"- engine vs top-10 mean: {100 * (mean(s.potency_per_s for s in sims[:10]) * scalar / mean(parse_target_dps(p) for p in top) - 1):+.2f}%"
              " (by construction the all-parse mean is 0; this is the top-10 slice)", "",
              "The scalar absorbs everything that is not rotation: gear, party buffs received, real movement "
              "and downtime. Judge the rotation from the tables below, never from this number.", "",
              "## 2. Casts per minute", "", "| action | engine | top 10 | all parses | engine vs top 10 |",
              "|---|---:|---:|---:|---:|"]
    sim_casts = lambda key: mean(per_minute(s.casts, key, s.duration_s) for s in sims[:10])
    for key, name in NAMES.items():
        engine = sim_casts(key)
        best = mean(per_minute(p["casts"], name, p["duration_s"]) for p in top)
        everyone = mean(per_minute(p["casts"], name, p["duration_s"]) for p in parses)
        delta = f"{100 * (engine / best - 1):+.1f}%" if best else "n/a"
        lines.append(f"| {name} | {engine:.3f} | {best:.3f} | {everyone:.3f} | {delta} |")
    gcd_engine = mean(60 * sum(1 for e in s.log if e["gcd"] and e["t"] >= 0) / s.duration_s for s in sims[:10])
    gcd_top = mean(60 * p["gcd_count"] / p["duration_s"] for p in top)
    lines.append(f"| all weaponskills | {gcd_engine:.3f} | {gcd_top:.3f} | "
                 f"{mean(60 * p['gcd_count'] / p['duration_s'] for p in parses):.3f} | {100 * (gcd_engine / gcd_top - 1):+.1f}% |")

    lines += ["", "## 3. Hypercharge and Wildfire", ""]
    flat = [n for p in parses for n in p.get("blazing_per_hypercharge", [])]
    if flat:
        lines.append(f"- parses: {100 * sum(1 for n in flat if n == 5) / len(flat):.1f}% of Hypercharges hold five "
                     f"Blazing Shots (mean {mean(flat):.2f}); the engine always fits five offline")
    gaps = [g for p in parses for g in p.get("wildfire_minus_hypercharge_s", [])]
    if gaps:
        lines.append(f"- parses: Wildfire lands a median {statistics.median(gaps):+.2f} s from the nearest "
                     "Hypercharge (positive = after it); the engine weaves it about +0.6 s after")
    lines.append(f"- potions per parse: {mean(p.get('potions') or 0 for p in parses):.2f}")

    lines += ["", "## 4. Opener", ""]
    common = Counter(tuple(p.get("first_gcds", [])[:12]) for p in top).most_common(1)
    if common:
        lines.append(f"- most common first 12 weaponskills in the top 10 ({common[0][1]} of {len(top)}): "
                     + ", ".join(common[0][0]))
    engine_gcds = [NAMES.get(e["name"], e["name"]) for e in sims[0].log if e["gcd"]][:12]
    lines.append("- engine: " + ", ".join(engine_gcds))

    lines += ["", "## 5. Damage shares (auto attacks excluded)", "", "| source | engine | top 10 |", "|---|---:|---:|"]
    engine_total = mean(sum(s.damage_by_action.values()) for s in sims[:10]) or 1.0

    def engine_share(prefixes: Tuple[str, ...]) -> float:
        return mean(sum(v for k, v in s.damage_by_action.items() if k.startswith(prefixes)) for s in sims[:10]) / engine_total

    def parse_share(names: Tuple[str, ...]) -> float:
        return mean(sum(v for k, v in p["damage_share"].items() if k in names) / (1 - (p.get("auto_attack_share") or 0))
                    for p in top)
    rows = [("Automaton Queen", ("Queen:",), tuple(QUEEN_COEFFICIENTS)), ("Wildfire", ("Wildfire",), ("Wildfire",)),
            ("Drill", ("Drill",), ("Drill",)), ("Blazing Shot", ("BlazingShot",), ("Blazing Shot",)),
            ("Double Check + Checkmate", ("DoubleCheck", "Checkmate"), ("Double Check", "Checkmate")),
            ("Heated combo", ("Heated",), ("Heated Split Shot", "Heated Slug Shot", "Heated Clean Shot")),
            ("Air Anchor", ("AirAnchor",), ("Air Anchor",)),
            ("Chain Saw + Excavator", ("ChainSaw", "Excavator"), ("Chain Saw", "Excavator")),
            ("Full Metal Field", ("FullMetalField",), ("Full Metal Field",))]
    for label, prefixes, names in rows:
        lines.append(f"| {label} | {100 * engine_share(prefixes):.2f}% | {100 * parse_share(names):.2f}% |")

    lines += ["", "## 6. Automaton Queen hit timeline", ""]
    if queen:
        assumed = tables["job"]["queen"]["hits"]
        lines += ["| # | measured hit | seconds after summon | simulator assumed |", "|---:|---|---:|---|"]
        for index, hit in enumerate(queen):
            was = f"{assumed[index]['name']} at {assumed[index]['offset_s']}" if index < len(assumed) else "-"
            lines.append(f"| {index + 1} | {hit['name']} | {hit['offset_s']:.2f} | {was} |")
        total = sum(h["per_battery"] for h in queen)
        lines += ["", f"Measured sequence totals {total:.1f} potency per battery (The Balance: 26.6)."]
    else:
        lines.append("No complete summons found in the summary.")
    lines += ["", "## 7. Queen summon times, top parse", "",
              ", ".join(f"{t:.0f}" for t in parses[0].get("queen_summons_s", [])) + " s", "",
              "engine at that length: " + ", ".join(f"{t:.0f} ({b})" for t, b in sims[0].queens) + " s (battery)"]
    return "\n".join(lines) + "\n"


def write_back(scalar: float, auto_share: float, queen: List[Dict[str, Any]]) -> None:
    stats_path, job_path = DATA_DIR / "stats.json", DATA_DIR / "job.json"
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    stats["potency_to_damage"] = round(scalar, 4)
    stats["auto_attack_share"] = round(auto_share, 5)
    stats["_notes"] = ("potency_to_damage and auto_attack_share were fitted by sim_mch.calibrate against "
                       "mch-analysis/output/summary.json; the stat profile itself is the Bard simulator's.")
    stats_path.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    if queen:
        job = json.loads(job_path.read_text(encoding="utf-8"))
        job["queen"]["hits"] = queen
        job["queen"]["_hits_note"] = ("Sequence and offsets measured by sim_mch.calibrate from the parse summary; "
                                      "coefficients are the job guide's potency per point of battery.")
        job_path.write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--out", type=Path, default=None, help="write the markdown report here")
    parser.add_argument("--write", action="store_true", help="store the fitted scalar, auto-attack share and "
                        "Queen timeline in sim_mch/data")
    args = parser.parse_args(argv)
    if not args.summary.exists():
        raise SystemExit(f"{args.summary} not found: run mch-analysis/collect.py first")
    parses = sorted(json.loads(args.summary.read_text(encoding="utf-8"))["parses"], key=lambda p: p["rank"])
    tables = load_tables()
    sims = [simulate_parse(p, tables) for p in parses]
    scalar = fit_scalar(parses, sims)
    queen = queen_timeline(parses)
    report = build_report(parses, sims, scalar, queen, tables)
    print(report)
    if args.out:
        args.out.write_text(report, encoding="utf-8")
    if args.write:
        write_back(scalar, mean(p.get("auto_attack_share") or 0 for p in parses), queen)
    return 0


if __name__ == "__main__":
    sys.exit(main())
