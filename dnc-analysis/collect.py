#!/usr/bin/env python3
"""Collect and summarise the top Dancer parses for one encounter from FFLogs.

    export FFLOGS_CLIENT_ID=...  FFLOGS_CLIENT_SECRET=...
    python dnc-analysis/collect.py --top 40

Shares the network layer with `mch-analysis/collect.py`. Credentials come from the
environment only. Raw event streams are cached under `output/events/` (git-ignored); the
only file meant for version control is `output/summary.json`, which holds per-parse
aggregates and no character names. `sim_dnc.calibrate` reads it.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("ciel_fflogs", HERE.parent / "mch-analysis" / "collect.py")
fflogs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fflogs)

STEPS = {"Emboite", "Entrechat", "Jete", "Pirouette"}
WEAPONSKILLS = {
    "Cascade", "Fountain", "Reverse Cascade", "Fountainfall", "Windmill", "Bladeshower", "Rising Windmill",
    "Bloodshower", "Saber Dance", "Dance of the Dawn", "Tillana", "Starfall Dance", "Last Dance", "Finishing Move",
    "Standard Step", "Technical Step",
}
BURST_GCDS = ("Tillana", "Dance of the Dawn", "Last Dance", "Finishing Move", "Saber Dance", "Starfall Dance")
AUTO_ATTACKS = {"Shot", "attack", "Attack"}


def summarise(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Per-parse aggregates. Pure function of one cached parse; no names, no raw events."""
    names = raw["abilities"]
    start, end = raw["start"], raw["end"]
    duration = (end - start) / 1000.0

    def name_of(event: dict) -> str:
        return names.get(str(event.get("abilityGameID")), str(event.get("abilityGameID")))

    sequence = sorted(((e["timestamp"] - start) / 1000.0, name_of(e)) for e in raw["casts"] if e.get("type") == "cast")
    # FFLogs logs a finish twice (the cast and its party-wide application); keep one per 3 s.
    cleaned, last_finish = [], -99.0
    for t, name in sequence:
        if "Finish" in name and "Improvised" not in name:
            if t - last_finish < 3.0:
                continue
            last_finish = t
        cleaned.append((t, name))
    sequence = cleaned
    casts: Dict[str, int] = {}
    for _, name in sequence:
        casts[name] = casts.get(name, 0) + 1

    damage: Dict[str, float] = {}
    for e in raw["damage"]:
        if e.get("type") == "damage":
            damage[name_of(e)] = damage.get(name_of(e), 0.0) + float(e.get("amount", 0))
    grand = sum(damage.values())

    buff_events = sorted((e for e in raw.get("medicated", []) if e.get("targetID") == e.get("sourceID")),
                         key=lambda e: e["timestamp"])
    potions = sum(1 for e in buff_events if e.get("type") == "applybuff")
    if buff_events and buff_events[0].get("type") == "removebuff":
        potions += 1
    potions = max(potions, sum(v for k, v in casts.items() if "Gemdraught" in k or "Tincture" in k))

    technical = [t for t, n in sequence if "Technical Finish" in n]
    bursts: List[List[str]] = []
    devilment_gap: List[float] = []
    for tf in technical:
        bursts.append([n for t, n in sequence if 0 < t - tf <= 20.5 and n in BURST_GCDS])
        nearest = [t - tf for t, n in sequence if n == "Devilment" and -10 <= t - tf <= 10]
        if nearest:
            devilment_gap.append(round(min(nearest, key=abs), 2))
    standard_before_technical = []
    for ts in (t for t, n in sequence if n == "Technical Step"):
        earlier = [ts - t for t, n in sequence if "Standard Finish" in n and 0 <= ts - t <= 30]
        if earlier:
            standard_before_technical.append(round(min(earlier), 2))

    gcds = [(t, n) for t, n in sequence if n in WEAPONSKILLS or "Finish" in n and "Improvised" not in n]
    autos = sum(v for k, v in damage.items() if k in AUTO_ATTACKS)
    return {
        "rank": raw["rank"], "amount": raw.get("amount"), "aDPS": raw.get("aDPS"), "rDPS": raw.get("rDPS"),
        "nDPS": raw.get("nDPS"), "report_code": raw["report_code"], "fight_id": raw["fight_id"],
        "duration_s": round(duration, 3),
        "casts": dict(sorted((k, v) for k, v in casts.items() if k not in STEPS)),
        "steps": sum(v for k, v in casts.items() if k in STEPS),
        "gcd_count": len(gcds),
        "damage_share": {k: round(v / grand, 5) for k, v in sorted(damage.items()) if grand},
        "auto_attack_share": round(autos / grand, 5) if grand else 0.0,
        "potions": potions,
        "burst_gcds": bursts,
        "devilment_minus_technical_finish_s": devilment_gap,
        "standard_finish_before_technical_step_s": standard_before_technical,
        "opener": [n for _, n in sequence if n not in STEPS][:24],
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--encounter", type=int, default=101, help="FFLogs encounter id (101 = Vamp Fatale)")
    parser.add_argument("--top", type=int, default=40)
    parser.add_argument("--output", type=Path, default=HERE / "output")
    parser.add_argument("--summarise-only", action="store_true")
    args = parser.parse_args(argv)
    events_dir = args.output / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    if not args.summarise_only:
        fflogs.collect_all("Dancer", args.encounter, args.top, events_dir, args.output / "errors.json")
    rows = [summarise(json.loads(p.read_text(encoding="utf-8"))) for p in sorted(events_dir.glob("rank-*.json"))]
    if not rows:
        raise SystemExit("no cached parses to summarise")
    (args.output / "summary.json").write_text(json.dumps({"encounter": args.encounter, "parses": rows}, indent=1),
                                              encoding="utf-8")
    durations = [r["duration_s"] for r in rows]
    print(f"{len(rows)} parses summarised; duration {min(durations):.0f}-{max(durations):.0f}s, "
          f"median amount {statistics.median(r['amount'] or 0 for r in rows):,.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
