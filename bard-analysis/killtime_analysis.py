#!/usr/bin/env python3
"""Measure Bard kill timing against actual final burst casts in FFLogs."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import os
import statistics
import sys
import time
import base64
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


TOKEN_URL = "https://www.fflogs.com/oauth/token"
API_URL = "https://www.fflogs.com/api/v2/client"

RANKINGS_QUERY = """
query Rankings($page: Int!) {
  worldData {
    encounter(id: 101) {
      name
      characterRankings(
        className: "Global"
        specName: "Bard"
        metric: dps
        page: $page
      )
    }
  }
}
"""

FIGHT_QUERY = """
query Fight($code: String!, $fightIDs: [Int]) {
  reportData {
    report(code: $code) {
      fights(fightIDs: $fightIDs) {
        id startTime endTime friendlyPlayers
      }
      masterData {
        actors { id name type subType }
        abilities { gameID name }
      }
    }
  }
}
"""

CASTS_QUERY = """
query Casts($code: String!, $fightIDs: [Int], $sourceID: Int) {
  reportData {
    report(code: $code) {
      events(
        fightIDs: $fightIDs
        sourceID: $sourceID
        dataType: Casts
        limit: 10000
      ) { data nextPageTimestamp }
    }
  }
}
"""

BURST_ACTIONS = {"Raging Strikes", "Battle Voice", "Radiant Finale"}


class FFLogs:
    def __init__(self, client_id: str, client_secret: str) -> None:
        body = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
        request = urllib.request.Request(TOKEN_URL, data=body)
        basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        request.add_header("Authorization", f"Basic {basic}")
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(request, timeout=30) as response:
            self.token = json.load(response)["access_token"]

    def query(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps({"query": query, "variables": variables}).encode()
        request = urllib.request.Request(API_URL, data=body)
        request.add_header("Authorization", f"Bearer {self.token}")
        request.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.load(response)
        if payload.get("errors"):
            raise RuntimeError(payload["errors"])
        return payload["data"]


def find_bard_actor(
    actors: list[dict[str, Any]], friendly_ids: list[int], ranking_name: str
) -> dict[str, Any]:
    friendly = set(friendly_ids)
    bards = [
        actor
        for actor in actors
        if actor.get("id") in friendly and actor.get("subType") == "Bard"
    ]
    exact = [actor for actor in bards if actor.get("name") == ranking_name]
    if len(exact) == 1:
        return exact[0]
    if len(bards) == 1:
        return bards[0]
    raise RuntimeError(
        f"Could not uniquely resolve Bard actor for {ranking_name!r}: {bards!r}"
    )


def analyze_one(api: FFLogs, rank: int, ranking: dict[str, Any]) -> dict[str, Any]:
    report = ranking["report"]
    code = report["code"]
    fight_id = report["fightID"]
    data = api.query(FIGHT_QUERY, {"code": code, "fightIDs": [fight_id]})
    node = data["reportData"]["report"]
    fight = node["fights"][0]
    actor = find_bard_actor(
        node["masterData"]["actors"], fight["friendlyPlayers"], ranking["name"]
    )
    ability_names = {
        item["gameID"]: item["name"] for item in node["masterData"]["abilities"]
    }
    casts_data = api.query(
        CASTS_QUERY,
        {"code": code, "fightIDs": [fight_id], "sourceID": actor["id"]},
    )
    event_node = casts_data["reportData"]["report"]["events"]
    if event_node.get("nextPageTimestamp") is not None:
        raise RuntimeError("Unexpected pagination for source-filtered cast stream")

    start = fight["startTime"]
    end = fight["endTime"]
    burst_casts: dict[str, list[float]] = {name: [] for name in BURST_ACTIONS}
    for event in event_node["data"]:
        name = ability_names.get(event.get("abilityGameID"))
        if name in BURST_ACTIONS and event.get("type") == "cast":
            burst_casts[name].append((event["timestamp"] - start) / 1000)

    final = {name: (max(times) if times else None) for name, times in burst_casts.items()}
    duration = (end - start) / 1000
    final_anchor_candidates = [
        value for key, value in final.items() if key in {"Battle Voice", "Radiant Finale"} and value is not None
    ]
    final_anchor = min(final_anchor_candidates) if final_anchor_candidates else None
    return {
        "rank": rank,
        "name": ranking["name"],
        "amount": ranking["amount"],
        "aDPS": ranking.get("aDPS"),
        "rDPS": ranking.get("rDPS"),
        "nDPS": ranking.get("nDPS"),
        "duration_s": duration,
        "report_code": code,
        "fight_id": fight_id,
        "bard_actor_id": actor["id"],
        "final_raging_s": final["Raging Strikes"],
        "final_battle_voice_s": final["Battle Voice"],
        "final_radiant_finale_s": final["Radiant Finale"],
        "final_party_anchor_s": final_anchor,
        "death_after_final_anchor_s": (
            duration - final_anchor if final_anchor is not None else None
        ),
        "rough_cycle_phase_s": duration % 120,
        "burst_casts": burst_casts,
    }


def bucket(seconds: float | None) -> str:
    if seconds is None:
        return "missing"
    if seconds < 20:
        return "<20"
    if seconds <= 30:
        return "20-30"
    if seconds <= 45:
        return "31-45"
    if seconds <= 60:
        return "46-60"
    return "61+"


def markdown_report(rows: list[dict[str, Any]]) -> str:
    usable = [r for r in rows if r.get("death_after_final_anchor_s") is not None]
    gaps = [r["death_after_final_anchor_s"] for r in usable]
    counts: dict[str, int] = {}
    adps_by_band: dict[str, list[float]] = {"<20": [], "20-30": [], "31+": []}
    for row in rows:
        key = bucket(row.get("death_after_final_anchor_s"))
        counts[key] = counts.get(key, 0) + 1
        gap = row.get("death_after_final_anchor_s")
        if gap is not None and row.get("aDPS") is not None:
            broad_band = "<20" if gap < 20 else ("20-30" if gap <= 30 else "31+")
            adps_by_band[broad_band].append(row["aDPS"])
    lines = [
        "# Vamp Fatale Bard Kill-Time Analysis",
        "",
        "This measures death time against each Bard's actual final Battle Voice/Radiant Finale window, not merely `duration % 120`.",
        "",
        "## Summary",
        "",
        f"- Parses analyzed: {len(rows)}",
        f"- Parses with a resolved final burst anchor: {len(usable)}",
    ]
    if gaps:
        lines.extend(
            [
                f"- Median death after final buff anchor: {statistics.median(gaps):.3f}s",
                f"- Range: {min(gaps):.3f}s to {max(gaps):.3f}s",
            ]
        )
    lines.extend(["", "## Distribution", "", "| Window | Parses |", "|---|---:|"])
    for key in ("<20", "20-30", "31-45", "46-60", "61+", "missing"):
        label = key if key == "missing" else f"{key}s"
        lines.append(f"| {label} | {counts.get(key, 0)} |")
    lines.extend(
        [
            "",
            "## Broad timing-band aDPS",
            "",
            "| Death after final anchor | Parses | Mean aDPS |",
            "|---|---:|---:|",
        ]
    )
    for key in ("<20", "20-30", "31+"):
        values = adps_by_band[key]
        mean = statistics.mean(values) if values else float("nan")
        lines.append(f"| {key}s | {len(values)} | {mean:.1f} |")
    lines.extend(
        [
            "",
            "## Parse-level timings",
            "",
            "| Rank | Player | Duration | Final BV | Final RF | Death after anchor | aDPS | rDPS |",
            "|---:|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in sorted(rows, key=lambda r: r["rank"]):
        def f(value: float | None) -> str:
            return "—" if value is None else f"{value:.3f}"
        lines.append(
            f"| {row['rank']} | {row['name']} | {f(row['duration_s'])} | "
            f"{f(row['final_battle_voice_s'])} | {f(row['final_radiant_finale_s'])} | "
            f"{f(row['death_after_final_anchor_s'])} | {f(row.get('aDPS'))} | {f(row.get('rDPS'))} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation guardrails",
            "",
            "- The anchor is the earlier of the Bard's final Battle Voice and Radiant Finale casts.",
            "- This identifies burst-window truncation/dilution; it does not by itself prove causality.",
            "- Final recommendations must be merged with action timelines, party buffs, RNG, and encounter downtime.",
            "- Anonymous/private reports can be unavailable or actor resolution can be ambiguous; failures are retained separately.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=40)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--output", type=Path, default=Path("output/killtime"))
    args = parser.parse_args()
    client_id = os.environ.get("FFLOGS_CLIENT_ID")
    client_secret = os.environ.get("FFLOGS_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("Set FFLOGS_CLIENT_ID and FFLOGS_CLIENT_SECRET", file=sys.stderr)
        return 2

    api = FFLogs(client_id, client_secret)
    rankings = api.query(RANKINGS_QUERY, {"page": 1})["worldData"]["encounter"]["characterRankings"]["rankings"][: args.top]
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(analyze_one, api, rank, item): (rank, item)
            for rank, item in enumerate(rankings, 1)
        }
        for completed, future in enumerate(concurrent.futures.as_completed(futures), 1):
            rank, item = futures[future]
            try:
                rows.append(future.result())
                print(f"[{completed}/{len(futures)}] rank {rank} complete", flush=True)
            except Exception as exc:  # retain failures for audit instead of hiding them
                errors.append({"rank": rank, "name": item.get("name"), "error": str(exc)})
                print(f"[{completed}/{len(futures)}] rank {rank} failed", flush=True)
            time.sleep(0.05)

    rows.sort(key=lambda row: row["rank"])
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "killtime.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    (args.output / "errors.json").write_text(json.dumps(errors, indent=2), encoding="utf-8")
    (args.output / "killtime-report.md").write_text(markdown_report(rows), encoding="utf-8")
    if rows:
        flat_rows = [{k: v for k, v in row.items() if k != "burst_casts"} for row in rows]
        with (args.output / "killtime.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(flat_rows[0]))
            writer.writeheader()
            writer.writerows(flat_rows)
    print(f"Completed {len(rows)} parses with {len(errors)} failures.")
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
