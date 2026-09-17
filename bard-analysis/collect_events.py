#!/usr/bin/env python3
"""Cache source-filtered Bard casts and damage events for resolved parses."""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

TOKEN_URL = "https://www.fflogs.com/oauth/token"
API_URL = "https://www.fflogs.com/api/v2/client"

QUERY = """
query Timeline($code: String!, $fightIDs: [Int], $sourceID: Int) {
  reportData {
    report(code: $code) {
      masterData { abilities { gameID name type } }
      casts: events(
        fightIDs: $fightIDs sourceID: $sourceID dataType: Casts limit: 10000
      ) { data nextPageTimestamp }
      damage: events(
        fightIDs: $fightIDs sourceID: $sourceID dataType: DamageDone limit: 10000
      ) { data nextPageTimestamp }
    }
  }
}
"""


def token(client_id: str, client_secret: str) -> str:
    request = urllib.request.Request(
        TOKEN_URL,
        data=urllib.parse.urlencode({"grant_type": "client_credentials"}).encode(),
    )
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    request.add_header("Authorization", f"Basic {basic}")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)["access_token"]


def fetch(access_token: str, row: dict[str, Any]) -> dict[str, Any]:
    variables = {
        "code": row["report_code"],
        "fightIDs": [row["fight_id"]],
        "sourceID": row["bard_actor_id"],
    }
    request = urllib.request.Request(
        API_URL, data=json.dumps({"query": QUERY, "variables": variables}).encode()
    )
    request.add_header("Authorization", f"Bearer {access_token}")
    request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=90) as response:
        payload = json.load(response)
    if payload.get("errors"):
        raise RuntimeError(payload["errors"])
    report = payload["data"]["reportData"]["report"]
    if report["casts"].get("nextPageTimestamp") or report["damage"].get("nextPageTimestamp"):
        raise RuntimeError("Timeline unexpectedly requires pagination")
    return {
        "parse": row,
        "abilities": report["masterData"]["abilities"],
        "casts": report["casts"]["data"],
        "damage": report["damage"]["data"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("output/killtime/killtime.json"))
    parser.add_argument("--output", type=Path, default=Path("output/events"))
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    cid = os.environ.get("FFLOGS_CLIENT_ID")
    secret = os.environ.get("FFLOGS_CLIENT_SECRET")
    if not cid or not secret:
        raise SystemExit("Set FFLOGS_CLIENT_ID and FFLOGS_CLIENT_SECRET")
    rows = json.loads(args.input.read_text())
    access_token = token(cid, secret)
    args.output.mkdir(parents=True, exist_ok=True)
    errors: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = {pool.submit(fetch, access_token, row): row for row in rows}
        for count, future in enumerate(concurrent.futures.as_completed(jobs), 1):
            row = jobs[future]
            try:
                result = future.result()
                path = args.output / f"rank-{row['rank']:02d}.json"
                path.write_text(json.dumps(result, separators=(",", ":")), encoding="utf-8")
                print(f"[{count}/{len(jobs)}] rank {row['rank']} cached", flush=True)
            except Exception as exc:
                errors.append({"rank": row["rank"], "name": row["name"], "error": str(exc)})
                print(f"[{count}/{len(jobs)}] rank {row['rank']} failed", flush=True)
    (args.output / "errors.json").write_text(json.dumps(errors, indent=2), encoding="utf-8")
    print(f"Finished with {len(errors)} errors.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
