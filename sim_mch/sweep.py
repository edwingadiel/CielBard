"""Sweep engine settings or fight parameters.

    python -m sim_mch.sweep --axis "hyperchargeBurstHeat=0,45" --axis "party_buffs=none,1.10"

Axis names are engine settings (dotted keys allowed) or the fight parameters `seconds`,
`kill_time_s`, `enemies`, `gcd_s`, `ping_ms`, `jitter_ms`, `potions`, `party_buffs`. The
rotation is deterministic, so every point is one fight and differences are exact, not
statistical -- unless `--jitter-ms` is set, in which case each point is averaged over
`--seeds`.
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
    parser.add_argument("--seeds", default="1", help="seed list or range; only matters with --jitter-ms")
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
        first = results[0]
        rows.append({
            **point,
            "dps": sum(r.dps for r in results) / len(results),
            "hypercharges": first.casts.get("Hypercharge", 0),
            "blazing_shots": first.casts.get("BlazingShot", 0),
            "queens": len(first.queens),
            "queen_battery": sum(b for _, b in first.queens),
            "wildfire_hits": "/".join(str(h) for h in first.wildfire_hits),
            "reassembles": first.casts.get("Reassemble", 0),
            "heat_wasted": first.stats["heat_wasted"],
            "battery_wasted": first.stats["battery_wasted"],
            "gcd_idle_s": round(first.stats["gcd_idle_s"], 2),
        })

    best = max(row["dps"] for row in rows)
    reference = rows[0]["dps"]
    for row in rows:
        row["vs_first_pct"] = round(100 * (row["dps"] / reference - 1), 3)
        row["dps"] = round(row["dps"], 1)
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
