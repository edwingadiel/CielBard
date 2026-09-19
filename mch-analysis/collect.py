#!/usr/bin/env python3
"""Collect and summarise the top Machinist parses for one encounter from FFLogs.

    export FFLOGS_CLIENT_ID=...       (PowerShell: $env:FFLOGS_CLIENT_ID = "...")
    export FFLOGS_CLIENT_SECRET=...
    python mch-analysis/collect.py --top 40

Credentials are read from the environment only and are never written anywhere. Raw event
streams are cached under `output/events/` (git-ignored); the only file meant for version
control is `output/summary.json`, which holds per-parse aggregates and no character names.
`sim_mch.calibrate` reads that summary.

`--summarise-only` rebuilds the summary from the cache without touching the network.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import statistics
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

TOKEN_URL = "https://www.fflogs.com/oauth/token"
API_URL = "https://www.fflogs.com/api/v2/client"
HERE = Path(__file__).resolve().parent

RANKINGS_QUERY = """
query Rankings($encounter: Int!, $page: Int!, $spec: String!) {
  worldData { encounter(id: $encounter) { name
    characterRankings(className: "Global", specName: $spec, metric: dps, page: $page) } }
}
"""

FIGHT_QUERY = """
query Fight($code: String!, $fightIDs: [Int]) {
  reportData { report(code: $code) {
    fights(fightIDs: $fightIDs) { id startTime endTime friendlyPlayers }
    masterData { actors { id name type subType petOwner } abilities { gameID name type } }
  } }
}
"""

EVENTS_QUERY = """
query Events($code: String!, $fightIDs: [Int], $sourceID: Int, $type: EventDataType!,
             $start: Float, $end: Float, $ability: Float) {
  reportData { report(code: $code) {
    events(fightIDs: $fightIDs, sourceID: $sourceID, dataType: $type, startTime: $start, endTime: $end, abilityID: $ability,
           limit: 10000) {
      data nextPageTimestamp }
  } }
}
"""

# Weaponskills, for GCD counting. Names, because parses are summarised by ability name.
WEAPONSKILLS = {
    "Heated Split Shot", "Heated Slug Shot", "Heated Clean Shot", "Drill", "Air Anchor", "Chain Saw",
    "Excavator", "Full Metal Field", "Blazing Shot", "Auto Crossbow", "Scattergun", "Bioblaster",
}
QUEEN_HITS = ("Roller Dash", "Arm Punch", "Pile Bunker", "Crowned Collider")
AUTO_ATTACKS = {"Shot", "attack", "Attack"}
MEDICATED = 1000049  # FFLogs reports statuses as 1,000,000 + status id


class FFLogs:
    def __init__(self, client_id: str, client_secret: str) -> None:
        body = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
        request = urllib.request.Request(TOKEN_URL, data=body)
        basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        request.add_header("Authorization", f"Basic {basic}")
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(request, timeout=30) as response:
            self.token = json.load(response)["access_token"]

    def query(self, query: str, variables: Dict[str, Any]) -> Dict[str, Any]:
        body = json.dumps({"query": query, "variables": variables}).encode()
        request = urllib.request.Request(API_URL, data=body)
        request.add_header("Authorization", f"Bearer {self.token}")
        request.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = json.load(response)
        if payload.get("errors"):
            raise RuntimeError(payload["errors"])
        return payload["data"]

    def events(self, code: str, fight_id: int, source_id: int, data_type: str, start: float, end: float,
               ability: Optional[int] = None) -> List[dict]:
        """Every event of one type from one source. FFLogs returns nothing when a start
        time is given without an end time, so both bounds are always sent."""
        out: List[dict] = []
        cursor: Optional[float] = start
        while cursor is not None:
            node = self.query(EVENTS_QUERY, {"code": code, "fightIDs": [fight_id], "sourceID": source_id,
                                             "type": data_type, "start": cursor, "end": end, "ability": ability})
            page = node["reportData"]["report"]["events"]
            out.extend(page["data"])
            cursor = page.get("nextPageTimestamp")
        return out


def resolve_actor(actors: List[dict], friendly: Iterable[int], name: str, spec: str = "Machinist") -> dict:
    friendly = set(friendly)
    jobs = [a for a in actors if a.get("id") in friendly and a.get("subType") == spec]
    exact = [a for a in jobs if a.get("name") == name]
    if len(exact) == 1:
        return exact[0]
    if len(jobs) == 1:
        return jobs[0]
    raise RuntimeError(f"could not resolve a unique {spec} among {len(jobs)} candidates")


def collect_one(api: FFLogs, rank: int, ranking: Dict[str, Any], spec: str = "Machinist") -> Dict[str, Any]:
    code, fight_id = ranking["report"]["code"], ranking["report"]["fightID"]
    node = api.query(FIGHT_QUERY, {"code": code, "fightIDs": [fight_id]})["reportData"]["report"]
    fight = node["fights"][0]
    actors = node["masterData"]["actors"]
    actor = resolve_actor(actors, fight["friendlyPlayers"], ranking["name"], spec)
    pets = [a for a in actors if a.get("petOwner") == actor["id"]]
    start, end = fight["startTime"], fight["endTime"]
    casts = api.events(code, fight_id, actor["id"], "Casts", start, end)
    damage = api.events(code, fight_id, actor["id"], "DamageDone", start, end)
    medicated = api.events(code, fight_id, actor["id"], "Buffs", start, end, MEDICATED)
    pet_damage: List[dict] = []
    for pet in pets:
        pet_damage += api.events(code, fight_id, pet["id"], "DamageDone", start, end)
    return {
        "rank": rank, "amount": ranking.get("amount"), "aDPS": ranking.get("aDPS"),
        "rDPS": ranking.get("rDPS"), "nDPS": ranking.get("nDPS"),
        "report_code": code, "fight_id": fight_id,
        "start": start, "end": fight["endTime"],
        "abilities": {str(a["gameID"]): a["name"] for a in node["masterData"]["abilities"]},
        "casts": casts, "damage": damage, "pet_damage": pet_damage, "medicated": medicated,
    }


def summarise(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Per-parse aggregates. Pure function of one cached parse; no names, no raw events."""
    names = raw["abilities"]
    start, end = raw["start"], raw["end"]
    duration = (end - start) / 1000.0

    def name_of(event: dict) -> str:
        return names.get(str(event.get("abilityGameID")), str(event.get("abilityGameID")))

    sequence = [((e["timestamp"] - start) / 1000.0, name_of(e)) for e in raw["casts"] if e.get("type") == "cast"]
    sequence.sort()
    casts: Dict[str, int] = {}
    for _, name in sequence:
        casts[name] = casts.get(name, 0) + 1

    def total(events: List[dict]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for e in events:
            if e.get("type") != "damage":
                continue
            out[name_of(e)] = out.get(name_of(e), 0.0) + float(e.get("amount", 0))
        return out

    # FFLogs already folds a pet's damage into its owner's stream, so the Queen's hits are
    # taken from the pet's own events and dropped from the player's to avoid counting twice.
    pet = total(raw["pet_damage"])
    player = {k: v for k, v in total(raw["damage"]).items() if k not in QUEEN_HITS}
    grand = sum(player.values()) + sum(pet.values())

    # Queen hit timeline: for every summon, her hits as (name, seconds after the summon).
    summons = [t for t, name in sequence if name == "Automaton Queen"]
    timelines: List[List[list]] = [[] for _ in summons]
    pet_hits = sorted(((e["timestamp"] - start) / 1000.0, name_of(e)) for e in raw["pet_damage"]
                      if e.get("type") == "damage" and name_of(e) in QUEEN_HITS)
    for t, hit in pet_hits:
        earlier = [i for i, s in enumerate(summons) if s <= t]
        if earlier and t - summons[earlier[-1]] <= 30:
            timelines[earlier[-1]].append([hit, round(t - summons[earlier[-1]], 2)])

    # Blazing Shots per Hypercharge and the gap from Hypercharge to Wildfire.
    hypercharges = [t for t, name in sequence if name == "Hypercharge"]
    blazing = [t for t, name in sequence if name in ("Blazing Shot", "Auto Crossbow")]
    per_hypercharge = [sum(1 for b in blazing if h <= b < h + 10.5) for h in hypercharges]
    wildfire_gap = []
    for w in (t for t, name in sequence if name == "Wildfire"):
        nearest = min(hypercharges, key=lambda h: abs(h - w)) if hypercharges else None
        if nearest is not None:
            wildfire_gap.append(round(w - nearest, 2))

    # Potions. A pre-pull potion is pressed before the fight starts, so its cast is not in
    # the fight's events; it shows up as a Medicated buff that is removed without ever
    # having been applied.
    # The Queen mirrors the buff, so only events whose target is the player count.
    buff_events = sorted((e for e in raw.get("medicated", []) if e.get("targetID") == e.get("sourceID")),
                         key=lambda e: e["timestamp"])
    potions = sum(1 for e in buff_events if e.get("type") == "applybuff")
    if buff_events and buff_events[0].get("type") == "removebuff":
        potions += 1
    potions = max(potions, sum(v for k, v in casts.items() if "Gemdraught" in k or "Tincture" in k))

    gcds = [(t, name) for t, name in sequence if name in WEAPONSKILLS]
    autos = sum(v for k, v in player.items() if k in AUTO_ATTACKS)
    return {
        "rank": raw["rank"], "amount": raw.get("amount"), "aDPS": raw.get("aDPS"),
        "rDPS": raw.get("rDPS"), "nDPS": raw.get("nDPS"),
        "report_code": raw["report_code"], "fight_id": raw["fight_id"],
        "duration_s": round(duration, 3),
        "event_dps": round(grand / duration, 2) if duration else 0.0,
        "casts": dict(sorted(casts.items())),
        "gcd_count": len(gcds),
        "damage_share": {k: round(v / grand, 5) for k, v in sorted({**player, **pet}.items()) if grand},
        "queen_share": round(sum(pet.values()) / grand, 5) if grand else 0.0,
        "auto_attack_share": round(autos / grand, 5) if grand else 0.0,
        "queen_summons_s": [round(t, 2) for t in summons],
        "queen_timelines": timelines,
        "blazing_per_hypercharge": per_hypercharge,
        "wildfire_minus_hypercharge_s": wildfire_gap,
        "barrel_stabilizer_s": [round(t, 2) for t, n in sequence if n == "Barrel Stabilizer"],
        "wildfire_s": [round(t, 2) for t, n in sequence if n == "Wildfire"],
        "reassemble_s": [round(t, 2) for t, n in sequence if n == "Reassemble"],
        "potions": potions,
        "opener": [name for _, name in sequence[:30]],
        "first_gcds": [name for _, name in gcds[:14]],
    }


def fetch_rankings(api: FFLogs, encounter: int, spec: str, top: int) -> List[dict]:
    rankings: List[dict] = []
    page = 1
    while len(rankings) < top:
        node = api.query(RANKINGS_QUERY, {"encounter": encounter, "page": page, "spec": spec})
        block = node["worldData"]["encounter"]["characterRankings"]
        rankings += block.get("rankings", [])
        if not block.get("hasMorePages"):
            break
        page += 1
    return rankings[:top]


def collect_all(spec: str, encounter: int, top: int, events_dir: Path, errors_path: Path) -> None:
    """Cache the raw events of the top `top` parses of `spec`. Shared by every job's study."""
    cid, secret = os.environ.get("FFLOGS_CLIENT_ID"), os.environ.get("FFLOGS_CLIENT_SECRET")
    if not cid or not secret:
        raise SystemExit("Set FFLOGS_CLIENT_ID and FFLOGS_CLIENT_SECRET in the environment.")
    api = FFLogs(cid, secret)
    errors = []
    for rank, ranking in enumerate(fetch_rankings(api, encounter, spec, top), start=1):
        path = events_dir / f"rank-{rank:02d}.json"
        if path.exists() and json.loads(path.read_text(encoding="utf-8")).get("casts"):
            print(f"[{rank}/{top}] cached")
            continue
        try:
            raw = collect_one(api, rank, ranking, spec)
            path.write_text(json.dumps(raw, separators=(",", ":")), encoding="utf-8")
            print(f"[{rank}/{top}] collected", flush=True)
        except Exception as exc:  # one private or malformed log must not stop the run
            errors.append({"rank": rank, "error": str(exc)})
            print(f"[{rank}/{top}] failed: {exc}", flush=True)
    if errors:
        errors_path.write_text(json.dumps(errors, indent=2), encoding="utf-8")


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
        collect_all("Machinist", args.encounter, args.top, events_dir, args.output / "errors.json")

    rows = [summarise(json.loads(path.read_text(encoding="utf-8"))) for path in sorted(events_dir.glob("rank-*.json"))]
    if not rows:
        raise SystemExit("no cached parses to summarise")
    summary = {"encounter": args.encounter, "parses": rows}
    (args.output / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    durations = [r["duration_s"] for r in rows]
    print(f"{len(rows)} parses summarised; duration {min(durations):.0f}-{max(durations):.0f}s, "
          f"median amount {statistics.median(r['amount'] or 0 for r in rows):,.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
