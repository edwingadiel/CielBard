"""Sweep engine settings or fight parameters.

    python -m sim_dnc.sweep --seeds 1-40 --axis "saberOffcycleEsprit=70,80,90"

Axis names are engine settings (dotted keys allowed) or the fight parameters `seconds`,
`kill_time_s`, `enemies`, `gcd_s`, `ping_ms`, `potions`, `party_buffs`, `ally_esprit_chance`.
Dancer is random, so every point is averaged over `--seeds` and the same seeds are used at
every point (a paired comparison): `sem` is the standard error of the paired difference
against the first row, which is what decides whether a difference is real.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import sys
from dataclasses import replace
from typing import Any, Dict, List, Optional, Tuple

from .core import FightConfig, config_fields, load_tables, parse_value, simulate, standard_party_buffs
from .run import add_fight_arguments, config_from_args


def apply_point(base: FightConfig, point: Dict[str, Any]) -> FightConfig:
    engine = dict(base.engine)
    changes: Dict[str, Any] = {}
    for key, value in point.items():
        if key == "party_buffs":
            changes[key] = () if value in (None, "none", 0, False) else standard_party_buffs(float(value))
        elif key in config_fields():
            changes[key] = value
        else:
            engine[key] = value
    return replace(base, engine=engine, **changes)


def parse_seeds(text: str) -> List[int]:
    if "-" in text:
        low, high = text.split("-", 1)
        return list(range(int(low), int(high) + 1))
    return [int(part) for part in text.split(",")]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_fight_arguments(parser)
    parser.add_argument("--axis", action="append", required=True, metavar="NAME=V1,V2,...")
    parser.add_argument("--over", action="append", default=[], metavar="NAME=V1,V2,...",
                        help="like --axis, but every point is averaged over these values "
                             "(e.g. several fight lengths, so one end-of-fight accident does not decide)")
    parser.add_argument("--kill-at-end", action="store_true",
                        help="the target dies at `seconds`, so the engine's terminal band is exercised")
    parser.add_argument("--seeds", default="1-24", help="seed list or range (default 1-24)")
    parser.add_argument("--csv", default=None)
    args = parser.parse_args(argv)

    axes: List[Tuple[str, List[Any]]] = []
    for item in args.axis:
        name, _, values = item.partition("=")
        axes.append((name.strip(), [parse_value(v) for v in values.split(",")]))
    over: List[Tuple[str, List[Any]]] = []
    for item in args.over:
        name, _, values = item.partition("=")
        over.append((name.strip(), [parse_value(v) for v in values.split(",")]))
    base = config_from_args(args)
    seeds = parse_seeds(args.seeds)
    tables = load_tables()

    rows = []
    for combo in itertools.product(*(values for _, values in axes)):
        point = {name: value for (name, _), value in zip(axes, combo)}
        results = []
        for extra in itertools.product(*(values for _, values in over)):
            full = {**point, **{name: value for (name, _), value in zip(over, extra)}}
            cfg = apply_point(base, full)
            if args.kill_at_end:
                cfg = replace(cfg, kill_time_s=cfg.seconds)
            results += [simulate(replace(cfg, seed=seed), tables) for seed in seeds]
        per_seed = {}
        for r, s in zip(results, [s for _ in range(max(1, len(results) // len(seeds))) for s in seeds]):
            per_seed.setdefault(s, []).append(r.dps)
        mean_of = lambda key: sum(r.casts.get(key, 0) for r in results) / len(results)
        rows.append({
            **point,
            "dps": sum(r.dps for r in results) / len(results),
            "_per_seed": {s: sum(v) / len(v) for s, v in per_seed.items()},
            "saber": round(mean_of("SaberDance"), 2),
            "fan_dance": round(mean_of("FanDance") + mean_of("FanDanceII"), 2),
            "last_dance": round(mean_of("LastDance"), 2),
            "esprit_wasted": round(sum(r.stats["esprit_wasted"] for r in results) / len(results), 1),
            "feathers_wasted": round(sum(r.stats["feathers_wasted"] for r in results) / len(results), 2),
            "lapsed": round(sum(sum(v for k, v in r.stats.items() if k.startswith("lapsed_")) for r in results) / len(results), 2),
        })

    best = max(row["dps"] for row in rows)
    reference = rows[0]["dps"]
    base_seeds = rows[0]["_per_seed"]
    for row in rows:
        diffs = [100 * (row["_per_seed"][s] / base_seeds[s] - 1) for s in base_seeds]
        mean_diff = sum(diffs) / len(diffs)
        sd = (sum((d - mean_diff) ** 2 for d in diffs) / max(1, len(diffs) - 1)) ** 0.5
        row["vs_first_pct"] = round(mean_diff, 3)
        row["sem_pct"] = round(sd / len(diffs) ** 0.5, 3)
        row["dps"] = round(row["dps"], 1)
        del row["_per_seed"]
    columns = list(rows[0].keys())
    widths = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in columns}
    print("  ".join(c.rjust(widths[c]) for c in columns))
    for row in rows:
        mark = " *" if abs(row["dps"] - round(best, 1)) < 0.05 else ""
        print("  ".join(str(row[c]).rjust(widths[c]) for c in columns) + mark)
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
