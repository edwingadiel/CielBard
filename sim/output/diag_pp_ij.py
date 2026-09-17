"""Instrumentation for the Pitch Perfect and Iron Jaws calibration gaps.

Monkeypatches sim.core.Simulation (never CielBard/) to record:
  - every Repertoire proc (time, song, stacks before/after, overcap, guaranteed)
  - every song start/end, with the Repertoire stacks discarded at the end
  - every Pitch Perfect cast (time, stacks spent, potency)
  - every DoT-applying cast (Iron Jaws / Stormbite / Caustic Bite) with the
    remaining DoT durations at the moment of the cast and the engine's decision
  - every DoT expiry on the primary target (a real fall-off)

Run from the repository root:
    python sim/output/diag_pp_ij.py --seeds 1-40 [--set k=v ...] [--json OUT]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from sim import core  # noqa: E402
from sim.runconfig import FightConfig  # noqa: E402

US = 1_000_000.0
DOT_KEYS = ("Stormbite", "CausticBite")


def parse_value(text):
    low = text.strip().lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def instrument():
    S = core.Simulation
    if getattr(S, "_diag_installed", False):
        return
    S._diag_installed = True

    orig_rep = S._repertoire_proc
    orig_end = S._end_song
    orig_start = S._start_song
    orig_special = S._apply_special
    orig_expire = S._handle_status_expire

    def log(self):
        d = getattr(self, "_diag", None)
        if d is None:
            d = self._diag = {
                "procs": [], "song_end": [], "song_start": [],
                "pp": [], "dotcast": [], "dotfall": [],
            }
        return d

    def _repertoire_proc(self, t_us, *, guaranteed=False):
        before = self.repertoire
        song = self.song
        ok = orig_rep(self, t_us, guaranteed=guaranteed)
        if ok:
            log(self)["procs"].append({
                "t": t_us / US, "song": song, "before": before,
                "after": self.repertoire, "guaranteed": guaranteed,
                "overcap": song == "WM" and before >= self._pp_max,
                "song_remaining": max(0.0, (self.song_ends_us - t_us) / US),
            })
        return ok

    def _end_song(self, t_us):
        if self.song is not None:
            log(self)["song_end"].append({
                "t": t_us / US, "song": self.song, "stacks": self.repertoire,
                "paeon": self.paeon_stacks,
                "early_by": max(0.0, (self.song_ends_us - t_us) / US),
            })
        return orig_end(self, t_us)

    def _start_song(self, code, t_us):
        log(self)["song_start"].append({"t": t_us / US, "song": code})
        return orig_start(self, code, t_us)

    def _dot_remaining(self, t_us):
        holder = self.entity_statuses.get(self.target_id) or {}
        out = {}
        for k in DOT_KEYS:
            inst = holder.get(k)
            out[k] = max(0.0, (inst.expires_us - t_us) / US) if inst is not None else 0.0
        return out

    def _apply_special(self, key, data, t_us, target_id, snapshot):
        if key == core.KEY_PITCH_PERFECT:
            stacks = max(1, min(self.repertoire, self._pp_max))
            log(self)["pp"].append({
                "t": t_us / US, "raw_stacks": self.repertoire, "stacks": stacks,
                "potency": int(self._pp_potency[stacks - 1]),
                "song": self.song,
                "song_remaining": max(0.0, (self.song_ends_us - t_us) / US) if self.song else 0.0,
            })
        if key in ("IronJaws", "Stormbite", "CausticBite"):
            rem = _dot_remaining(self, t_us)
            log(self)["dotcast"].append({
                "t": t_us / US, "key": key,
                "storm": rem["Stormbite"], "caustic": rem["CausticBite"],
                "decision": self._decision(),
            })
        return orig_special(self, key, data, t_us, target_id, snapshot)

    def _handle_status_expire(self, event):
        who = event.payload["who"]
        key = event.payload["key"]
        holder = self.entity_statuses.get(who) or {}
        inst = holder.get(key)
        real = (who == self.target_id and key in DOT_KEYS and inst is not None
                and inst.expires_us == event.payload["expires_us"])
        orig_expire(self, event)
        if real:
            log(self)["dotfall"].append({"t": event.t_us / US, "key": key})

    S._repertoire_proc = _repertoire_proc
    S._end_song = _end_song
    S._start_song = _start_song
    S._apply_special = _apply_special
    S._handle_status_expire = _handle_status_expire


def seed_range(text):
    if "-" in text:
        a, b = text.split("-", 1)
        return list(range(int(a), int(b) + 1))
    return [int(text)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="1-40")
    ap.add_argument("--seconds", type=float, default=510.0)
    ap.add_argument("--kill-time", type=float, default=None)
    ap.add_argument("--set", action="append", default=[])
    ap.add_argument("--job", action="append", default=[])
    ap.add_argument("--json", default=None)
    ap.add_argument("--dump-seed", type=int, default=None)
    args = ap.parse_args()

    instrument()
    engine = {}
    for item in args.set:
        k, _, v = item.partition("=")
        engine[k.strip()] = parse_value(v)
    job = {}
    for item in args.job:
        k, _, v = item.partition("=")
        job[k.strip()] = parse_value(v)

    seeds = seed_range(args.seeds)
    per_fight = []
    dumps = None
    for seed in seeds:
        cfg = FightConfig(
            seconds=args.seconds, seed=seed, ping_ms=0.0, pulse_ms=30,
            engine_config=engine, job_overrides=job, kill_time_s=args.kill_time,
            stat_overrides={"potency_to_damage": 132.401588},
        )
        simulation = core.Simulation(cfg)
        result = simulation.run()
        d = simulation._diag
        if args.dump_seed is not None and seed == args.dump_seed:
            dumps = d

        wm_procs = [p for p in d["procs"] if p["song"] == "WM"]
        wm_over = [p for p in wm_procs if p["overcap"]]
        wm_end_loss = [e for e in d["song_end"] if e["song"] == "WM"]
        pp = d["pp"]
        ij = [c for c in d["dotcast"] if c["key"] == "IronJaws"]
        storm = [c for c in d["dotcast"] if c["key"] == "Stormbite"]
        caustic = [c for c in d["dotcast"] if c["key"] == "CausticBite"]
        # Iron Jaws refresh waste: duration thrown away = (remaining at cast)
        ij_waste = sum(min(c["storm"], c["caustic"]) for c in ij)
        ij_snap = [c for c in ij if "snapshot" in c["decision"].lower()]
        ij_refresh = [c for c in ij if "snapshot" not in c["decision"].lower()]
        song_s = result.song_seconds
        ij_times = [c["t"] for c in ij]
        ij_gaps = [round(b - a, 2) for a, b in zip(ij_times, ij_times[1:])]
        # income accounting inside Wanderer's Minuet
        wm_tick = [p for p in wm_procs if not p["guaranteed"]]
        wm_emp = [p for p in wm_procs if p["guaranteed"]]
        stacks_spent = sum(p["stacks"] for p in pp)
        # Which GCDs occupied the refresh window that ended in a fall-off?
        refresh_w = float(engine.get("dotRefreshSeconds", 3.0))
        gcd_casts = [(c.t_s, c.key) for c in result.casts if c.is_gcd]
        blockers = Counter()
        seen_events = set()
        for fall in d["dotfall"]:
            bucket = round(fall["t"], 2)
            if bucket in seen_events:
                continue
            seen_events.add(bucket)
            for t, k in gcd_casts:
                if fall["t"] - refresh_w <= t < fall["t"]:
                    blockers[k] += 1
        fall_events = len(seen_events)

        per_fight.append({
            "seed": seed,
            "dps": result.dps,
            "potency": result.total_potency,
            "pp_casts": len(pp),
            "pp_potency": sum(p["potency"] for p in pp),
            "pp_stacks_hist": Counter(p["stacks"] for p in pp),
            "pp_in_wm_tail": sum(1 for p in pp if p["song_remaining"] <= 3.0),
            "rep_procs_wm": len(wm_procs),
            "rep_wm_tick": len(wm_tick),
            "rep_wm_empyreal": len(wm_emp),
            "pp_stacks_spent": stacks_spent,
            "pp_unspent_at_end": simulation.repertoire,
            "ij_gaps": ij_gaps,
            "rep_overcap_wm": len(wm_over),
            "rep_lost_at_song_end": sum(e["stacks"] for e in wm_end_loss),
            "rep_lost_events": sum(1 for e in wm_end_loss if e["stacks"] > 0),
            "wm_seconds": song_s.get("WM", 0.0),
            "wm_casts": result.song_casts.get("WM", 0),
            "wm_early_by": [round(e["early_by"], 2) for e in wm_end_loss],
            "ij_casts": len(ij),
            "ij_snapshot": len(ij_snap),
            "ij_refresh": len(ij_refresh),
            "ij_waste_s": ij_waste,
            "ij_rem_at_cast": [round(min(c["storm"], c["caustic"]), 2) for c in ij],
            "storm_casts": len(storm),
            "caustic_casts": len(caustic),
            "hard_recast": sum(1 for c in storm + caustic if c["t"] > 10.0),
            "dot_falloff": len(d["dotfall"]),
            "fall_events": fall_events,
            "blockers": blockers,
            "dot_uptime": dict(result.dot_uptime),
            "gcds": result.gcd_count,
            "counts": dict(result.action_counts),
        })

    n = len(per_fight)
    minutes = args.seconds / 60.0

    def mean(key):
        return sum(f[key] for f in per_fight) / n

    def sem(key):
        vals = [f[key] for f in per_fight]
        if len(vals) < 2:
            return 0.0
        return statistics.stdev(vals) / (len(vals) ** 0.5)

    hist = Counter()
    for f in per_fight:
        hist.update(f["pp_stacks_hist"])
    rem_hist = Counter()
    for f in per_fight:
        for r in f["ij_rem_at_cast"]:
            rem_hist[round(r)] += 1

    out = {
        "seeds": len(seeds), "seconds": args.seconds, "engine": engine, "job": job,
        "dps_mean": mean("dps"), "dps_sem": sem("dps"),
        "pp_casts": mean("pp_casts"), "pp_per_min": mean("pp_casts") / minutes,
        "pp_potency": mean("pp_potency"),
        "pp_stacks_hist": {str(k): v / n for k, v in sorted(hist.items())},
        "pp_in_wm_tail": mean("pp_in_wm_tail"),
        "rep_procs_wm": mean("rep_procs_wm"),
        "rep_wm_tick": mean("rep_wm_tick"),
        "rep_wm_empyreal": mean("rep_wm_empyreal"),
        "pp_stacks_spent": mean("pp_stacks_spent"),
        "pp_unspent_at_end": mean("pp_unspent_at_end"),
        "ij_gap_max": max(max(f["ij_gaps"], default=0.0) for f in per_fight),
        "ij_gap_median": statistics.median(
            [g for f in per_fight for g in f["ij_gaps"]] or [0.0]),
        "rep_overcap_wm": mean("rep_overcap_wm"),
        "rep_lost_at_song_end": mean("rep_lost_at_song_end"),
        "rep_lost_events": mean("rep_lost_events"),
        "wm_seconds": mean("wm_seconds"), "wm_casts": mean("wm_casts"),
        "ij_casts": mean("ij_casts"), "ij_per_min": mean("ij_casts") / minutes,
        "ij_snapshot": mean("ij_snapshot"), "ij_refresh": mean("ij_refresh"),
        "ij_waste_s": mean("ij_waste_s"),
        "ij_rem_hist": {str(k): v / n for k, v in sorted(rem_hist.items())},
        "storm_casts": mean("storm_casts"), "caustic_casts": mean("caustic_casts"),
        "hard_recast": mean("hard_recast"),
        "dot_falloff": mean("dot_falloff"),
        "fall_events": mean("fall_events"),
        "blockers": {k: round(v / n, 3) for k, v in sorted(
            sum((f["blockers"] for f in per_fight), Counter()).items(),
            key=lambda kv: -kv[1])},
        "gcds": mean("gcds"), "gcds_per_min": mean("gcds") / minutes,
        "dot_uptime": {
            k: sum(f["dot_uptime"].get(k, 0.0) for f in per_fight) / n
            for k in ("Stormbite", "CausticBite")
        },
    }
    print(json.dumps(out, indent=2))
    if args.json:
        payload = {"summary": out, "per_fight": [
            {k: (dict(v) if isinstance(v, Counter) else v) for k, v in f.items()}
            for f in per_fight]}
        if dumps is not None:
            payload["dump"] = dumps
        Path(args.json).write_text(json.dumps(payload, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
