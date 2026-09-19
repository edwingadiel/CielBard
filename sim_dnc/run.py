"""One Dancer fight: `python -m sim_dnc.run --seconds 360 --seed 3 --timeline 30`."""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from .core import FightConfig, load_tables, parse_value, simulate, simulate_many, standard_party_buffs


def add_fight_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--seconds", type=float, default=360.0, help="combat seconds to simulate")
    parser.add_argument("--kill-time", type=float, default=None,
                        help="target dies after this many seconds (drives the engine's TTK bands)")
    parser.add_argument("--enemies", type=int, default=1, help="clustered targets")
    parser.add_argument("--gcd", type=float, default=None, help="GCD in seconds (default 2.50)")
    parser.add_argument("--ping-ms", type=float, default=0.0, help="added to every animation lock")
    parser.add_argument("--no-party", action="store_true", help="solo dummy: no partner, no party Esprit")
    parser.add_argument("--ally-esprit-chance", type=float, default=None,
                        help="chance that an ally weaponskill gives 10 Esprit (default from job.json)")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--potions", type=int, default=0, help="Gemdraughts in the inventory")
    parser.add_argument("--party-buffs", type=float, default=None, metavar="MULT",
                        help="20 s party window every 120 s from 0:06 with this damage multiplier")
    parser.add_argument("--self-pull", action="store_true",
                        help="start out of combat with requireCombat off: the engine pre-pulls and pulls")
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                        help="engine setting override, dotted keys allowed (repeatable)")


def config_from_args(args: argparse.Namespace) -> FightConfig:
    engine = {}
    for item in args.set:
        key, _, value = item.partition("=")
        engine[key.strip()] = parse_value(value)
    if args.self_pull:
        engine.setdefault("requireCombat", False)
    return FightConfig(
        seconds=args.seconds, kill_time_s=args.kill_time, enemies=args.enemies, gcd_s=args.gcd,
        ping_ms=args.ping_ms, seed=args.seed, potions=args.potions,
        partner=not args.no_party, party_size=1 if args.no_party else 8,
        ally_esprit_chance=args.ally_esprit_chance,
        start_in_combat=not args.self_pull,
        party_buffs=standard_party_buffs(args.party_buffs) if args.party_buffs else (),
        engine=engine,
    )


STEPS = ("Emboite", "Entrechat", "Jete", "Pirouette")


def format_report(result, timeline_s: float = 0.0) -> str:
    lines = [f"duration {result.duration_s:.1f}s   expected DPS {result.dps:,.1f}   "
             f"potency/s {result.potency_per_s:.2f}"]
    total = sum(result.damage_by_action.values()) or 1.0
    lines.append("")
    lines.append(f"{'source':28s} {'casts':>6s} {'share':>7s}")
    for name, damage in sorted(result.damage_by_action.items(), key=lambda kv: -kv[1]):
        lines.append(f"{name:28s} {result.casts.get(name, '')!s:>6s} {100 * damage / total:6.2f}%")
    lines.append("")
    utility = {k: v for k, v in result.casts.items() if k not in result.damage_by_action and k not in STEPS}
    lines.append("other casts: " + ", ".join(f"{k} {v}" for k, v in sorted(utility.items())))
    lines.append("")
    for key, value in sorted(result.stats.items()):
        lines.append(f"  {key:28s} {value:8.2f}")
    if timeline_s > 0:
        lines.append("")
        for entry in result.log:
            if entry["t"] > timeline_s:
                break
            if entry["name"] in STEPS:
                continue
            lines.append(f"{entry['t']:7.2f} {'' if entry['gcd'] else '    '}{entry['name']}"
                         f"  esprit={entry['esprit']} feathers={entry['feathers']}")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_fight_arguments(parser)
    parser.add_argument("--timeline", type=float, default=0.0, metavar="SECONDS",
                        help="print the cast timeline up to this time")
    parser.add_argument("--seeds", type=int, default=0, metavar="N",
                        help="also run seeds 1..N and report the mean and spread of expected DPS")
    parser.add_argument("--json", default=None, help="write the result here")
    args = parser.parse_args(argv)

    tables = load_tables()
    result = simulate(config_from_args(args), tables)
    print(format_report(result, args.timeline))
    if args.seeds:
        results = simulate_many(config_from_args(args), range(1, args.seeds + 1), tables)
        values = [r.dps for r in results]
        mean = sum(values) / len(values)
        sd = (sum((v - mean) ** 2 for v in values) / max(1, len(values) - 1)) ** 0.5
        print(f"\nseeds 1-{args.seeds}: mean {mean:,.1f}  sd {sd:,.1f}  sem {sd / len(values) ** 0.5:,.1f}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(result.to_dict(include_log=True), handle, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
