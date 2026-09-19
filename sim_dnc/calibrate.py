"""Calibrate sim_dnc against the parse summary produced by `dnc-analysis/collect.py`.

    python -m sim_dnc.calibrate --out sim_dnc/output/calibration.md --write

Two values are fitted, in this order:

1. `ally_esprit.chance`: the chance that an ally's weaponskill or spell gives the dancer 10
   Esprit. The game only says it "differs according to job". It is fitted so the simulated
   Saber Dance + Dance of the Dawn rate matches the top parses, because Esprit income is the
   only thing that sets that rate.
2. `potency_to_damage`: sum(parse DPS without auto attacks) / sum(simulated potency per second).

Every parse is re-simulated at its own length (target dying at the end, the parse's potion
count, the engine pulling) on `--seeds` seeds, and the rotation is compared with the top 10.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from .core import DATA_DIR, ROOT, FightConfig, FightResult, load_tables, simulate

DEFAULT_SUMMARY = ROOT / "dnc-analysis" / "output" / "summary.json"

NAMES = {
    "Cascade": "Cascade", "Fountain": "Fountain", "ReverseCascade": "Reverse Cascade", "Fountainfall": "Fountainfall",
    "SaberDance": "Saber Dance", "DanceOfTheDawn": "Dance of the Dawn", "LastDance": "Last Dance",
    "FinishingMove": "Finishing Move", "StandardStep": "Standard Step", "TechnicalStep": "Technical Step",
    "Tillana": "Tillana", "StarfallDance": "Starfall Dance", "Flourish": "Flourish", "Devilment": "Devilment",
    "FanDance": "Fan Dance", "FanDanceIII": "Fan Dance III", "FanDanceIV": "Fan Dance IV",
}
BURST_GCDS = ("Tillana", "DanceOfTheDawn", "LastDance", "FinishingMove", "SaberDance", "StarfallDance")


def mean(values) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def simulate_parse(parse: Dict[str, Any], tables, seed: int, chance: Optional[float] = None) -> FightResult:
    seconds = float(parse["duration_s"])
    return simulate(FightConfig(seconds=seconds, kill_time_s=seconds, potions=int(parse.get("potions") or 0),
                                start_in_combat=False, seed=seed, ally_esprit_chance=chance,
                                engine={"requireCombat": False}), tables)


def target_dps(parse: Dict[str, Any]) -> float:
    return float(parse["amount"]) * (1.0 - float(parse.get("auto_attack_share") or 0.0))


def spender_rate(casts: Dict[str, int], duration: float, saber: str, dawn: str) -> float:
    return 60.0 * (casts.get(saber, 0) + casts.get(dawn, 0)) / duration


def fit_chance(parses: List[Dict[str, Any]], tables, seeds: List[int]) -> (float, List[tuple]):
    """Grid search, then linear interpolation to the top-10 Esprit-spender rate."""
    top = parses[:10]
    wanted = mean(spender_rate(p["casts"], p["duration_s"], "Saber Dance", "Dance of the Dawn") for p in top)
    grid = []
    for chance in (0.10, 0.15, 0.20, 0.25, 0.30):
        rate = mean(spender_rate(simulate_parse(p, tables, s, chance).casts, p["duration_s"], "SaberDance", "DanceOfTheDawn")
                    for p in top[:5] for s in seeds)
        grid.append((chance, rate))
    fitted = grid[-1][0]
    for (c0, r0), (c1, r1) in zip(grid, grid[1:]):
        if r0 <= wanted <= r1 and r1 > r0:
            fitted = c0 + (c1 - c0) * (wanted - r0) / (r1 - r0)
            break
    else:
        if wanted < grid[0][1]:
            fitted = grid[0][0]
    return round(fitted, 3), [(wanted, None)] + grid


def build_report(parses, sims: Dict[int, List[FightResult]], scalar: float, chance: float, grid, tables) -> str:
    top = parses[:10]
    top_sims = [r for p in top for r in sims[p["rank"]]]
    lines = ["# sim_dnc calibration", "",
             f"{len(parses)} parses, fight length {min(p['duration_s'] for p in parses):.0f}-"
             f"{max(p['duration_s'] for p in parses):.0f} s. Each was re-simulated at its own length with the shipped "
             f"engine defaults, the target dying at the end, the parse's potion count and the engine pulling, on "
             f"{len(next(iter(sims.values())))} seeds.", "",
             "## 1. Ally Esprit chance", "",
             f"Top-10 Saber Dance + Dance of the Dawn: **{grid[0][0]:.3f} per minute**. Simulated rate by chance:", "",
             "| chance | spenders per minute |", "|---:|---:|"]
    lines += [f"| {c:.2f} | {r:.3f} |" for c, r in grid[1:]]
    lines += ["", f"Fitted `ally_esprit.chance` = **{chance:.3f}** (community estimate: about 0.20).", "",
              "## 2. Damage scalar", ""]
    per_parse = {p["rank"]: mean(r.potency_per_s for r in sims[p["rank"]]) for p in parses}
    residuals = [100 * (per_parse[p["rank"]] * scalar / target_dps(p) - 1) for p in parses]
    auto = mean(p.get("auto_attack_share") or 0 for p in parses)
    lines += [f"- fitted `potency_to_damage` = **{scalar:.4f}** (was {tables['stats']['potency_to_damage']})",
              f"- auto attacks are {100 * auto:.2f}% of parse damage and are removed from the target",
              f"- residual: mean |error| {mean(abs(r) for r in residuals):.2f}%, worst {max(residuals, key=abs):+.2f}%",
              f"- engine vs top-10 mean: {100 * (mean(per_parse[p['rank']] for p in top) * scalar / mean(target_dps(p) for p in top) - 1):+.2f}%",
              "", "The scalar absorbs gear, party buffs received and real downtime. Judge the rotation from the tables below.",
              "", "## 3. Casts per minute", "", "| action | engine | top 10 | all parses | engine vs top 10 |",
              "|---|---:|---:|---:|---:|"]
    for key, name in NAMES.items():
        engine = mean(60 * r.casts.get(key, 0) / r.duration_s for r in top_sims)
        best = mean(60 * p["casts"].get(name, 0) / p["duration_s"] for p in top)
        everyone = mean(60 * p["casts"].get(name, 0) / p["duration_s"] for p in parses)
        lines.append(f"| {name} | {engine:.3f} | {best:.3f} | {everyone:.3f} | "
                     + (f"{100 * (engine / best - 1):+.1f}%" if best else "n/a") + " |")

    def engine_gcds(r: FightResult) -> float:
        steps = ("Emboite", "Entrechat", "Jete", "Pirouette")
        return 60 * sum(1 for e in r.log if e["gcd"] and e["t"] >= 0 and e["name"] not in steps) / r.duration_s
    e_gcd, p_gcd = mean(engine_gcds(r) for r in top_sims), mean(60 * p["gcd_count"] / p["duration_s"] for p in top)
    lines.append(f"| all weaponskills (steps excluded) | {e_gcd:.3f} | {p_gcd:.3f} | "
                 f"{mean(60 * p['gcd_count'] / p['duration_s'] for p in parses):.3f} | {100 * (e_gcd / p_gcd - 1):+.1f}% |")

    lines += ["", "## 4. Burst", ""]
    parse_orders = Counter(tuple(b[:6]) for p in parses for b in p["burst_gcds"])
    engine_orders: Counter = Counter()
    for r in top_sims:
        names = [(e["t"], e["name"]) for e in r.log]
        for tf in [t for t, n in names if n == "QuadrupleTechnicalFinish"]:
            engine_orders[tuple([NAMES.get(n, n) for t, n in names if 0 < t - tf <= 20.5 and n in BURST_GCDS][:6])] += 1
    total_p, total_e = sum(parse_orders.values()), sum(engine_orders.values())
    lines.append("First six burst weaponskills after Technical Finish:")
    lines.append("")
    lines.append("| order | parses | engine |")
    lines.append("|---|---:|---:|")
    for order, count in parse_orders.most_common(4):
        lines.append(f"| {' > '.join(order)} | {100 * count / total_p:.0f}% | {100 * engine_orders.get(order, 0) / max(1, total_e):.0f}% |")
    for order, count in engine_orders.most_common(2):
        if order not in dict(parse_orders.most_common(4)):
            lines.append(f"| {' > '.join(order)} | {100 * parse_orders.get(order, 0) / total_p:.0f}% | {100 * count / total_e:.0f}% |")
    gaps = [g for p in parses for g in p["devilment_minus_technical_finish_s"]]
    sf = [g for p in parses for g in p["standard_finish_before_technical_step_s"]]
    lines += ["", f"- Devilment lands a median {statistics.median(gaps):+.2f} s from Technical Finish in the parses; "
              "the engine weaves it directly behind the finish.",
              f"- The last Standard Finish lands a median {statistics.median(sf):.1f} s before Technical Step in the parses.",
              f"- Potions per parse: {mean(p.get('potions') or 0 for p in parses):.2f}.", "",
              "## 5. Opener", ""]
    common = Counter(tuple(p.get("opener", [])[:12]) for p in top).most_common(1)[0]
    lines.append(f"- most common in the top 10 ({common[1]} of {len(top)}): " + ", ".join(common[0]))
    steps = ("Emboite", "Entrechat", "Jete", "Pirouette")
    engine_open = [NAMES.get(e["name"], e["name"]).replace("DoubleStandardFinish", "Double Standard Finish")
                   .replace("QuadrupleTechnicalFinish", "Quadruple Technical Finish")
                   for e in sims[parses[0]["rank"]][0].log if e["t"] >= 0 and e["name"] not in steps][:12]
    lines.append("- engine (seed 1): " + ", ".join(engine_open))

    lines += ["", "## 6. What the engine throws away (per fight, top-10 lengths)", ""]
    for key in ("esprit_wasted", "feathers_wasted", "gcd_idle_s", "wrong_steps", "broken_combos"):
        lines.append(f"- {key}: {mean(r.stats.get(key, 0) for r in top_sims):.2f}")
    lapsed = Counter()
    for r in top_sims:
        for k, v in r.stats.items():
            if k.startswith(("lapsed_", "overwritten_")):
                lapsed[k] += v
    lines.append("- lapsed / overwritten procs: " + (", ".join(f"{k} {v / len(top_sims):.2f}" for k, v in sorted(lapsed.items())) or "none"))
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--seeds", type=int, default=4, help="seeds per parse")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--write", action="store_true", help="store the fitted values in sim_dnc/data")
    args = parser.parse_args(argv)
    if not args.summary.exists():
        raise SystemExit(f"{args.summary} not found: run dnc-analysis/collect.py first")
    parses = sorted(json.loads(args.summary.read_text(encoding="utf-8"))["parses"], key=lambda p: p["rank"])
    tables = load_tables()
    seeds = list(range(1, args.seeds + 1))
    chance, grid = fit_chance(parses, tables, seeds)
    sims = {p["rank"]: [simulate_parse(p, tables, s, chance) for s in seeds] for p in parses}
    scalar = sum(target_dps(p) for p in parses) / sum(mean(r.potency_per_s for r in sims[p["rank"]]) for p in parses)
    report = build_report(parses, sims, scalar, chance, grid, tables)
    print(report)
    if args.out:
        args.out.write_text(report, encoding="utf-8")
    if args.write:
        stats_path, job_path = DATA_DIR / "stats.json", DATA_DIR / "job.json"
        stats = json.loads(stats_path.read_text(encoding="utf-8"))
        stats["potency_to_damage"] = round(scalar, 4)
        stats["auto_attack_share"] = round(mean(p.get("auto_attack_share") or 0 for p in parses), 5)
        stats["_notes"] = ("potency_to_damage and auto_attack_share were fitted by sim_dnc.calibrate against "
                           "dnc-analysis/output/summary.json; the stat profile itself is the Bard simulator's.")
        stats_path.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
        job = json.loads(job_path.read_text(encoding="utf-8"))
        job["ally_esprit"]["chance"] = chance
        job_path.write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
