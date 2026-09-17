"""Local-only event analysis for the cached Bard parses.

This deliberately reads only output/events/rank-*.json and never reads or writes
the kill-time results.  It is intentionally descriptive: event exports do not
contain gauge/resource state, animation locks, or the complete party context.
"""
from __future__ import annotations

import json, math, statistics
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).parent
EVENT_DIR = ROOT / "output" / "events"
OUT_DIR = ROOT / "output" / "luna"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SONGS = ["The Wanderer's Minuet", "Mage's Ballad", "Army's Paeon"]
BURST = ["Raging Strikes", "Battle Voice", "Radiant Finale"]
CORE_GCD = {
    "Burst Shot", "Refulgent Arrow", "Iron Jaws", "Apex Arrow", "Blast Arrow",
    "Resonant Arrow", "Ladonsbite", "Rain of Death", "Shadowbite",
    "Stormbite", "Caustic Bite",
}
CORE = CORE_GCD | {
    "Heartbreak Shot", "Empyreal Arrow", "Pitch Perfect", "Sidewinder",
    "Barrage", "Radiant Encore", "Raging Strikes", "Battle Voice",
    "Radiant Finale", "Bard's Paean", "Troubadour", "Nature's Minne",
}
KEYS = ["Apex Arrow", "Blast Arrow", "Radiant Encore", "Empyreal Arrow",
        "Heartbreak Shot", "Iron Jaws", "Pitch Perfect"]

def pct(x):
    return round(100*x, 3) if x is not None else None

def med(xs):
    return statistics.median(xs) if xs else None

def load(path):
    d = json.loads(path.read_text())
    casts = d["casts"]
    t0 = min((e["timestamp"] for e in casts), default=0)
    amap = {a["gameID"]: a["name"] for a in d.get("abilities", [])}
    def named(e):
        return amap.get(e.get("abilityGameID"), f"ID:{e.get('abilityGameID')}")
    # Relative seconds are parse-local; they are sufficient for within-parse timing.
    for e in casts:
        e["_name"] = named(e)
        e["_s"] = (e["timestamp"] - t0) / 1000.0
    for e in d["damage"]:
        e["_name"] = named(e)
        e["_s"] = (e["timestamp"] - t0) / 1000.0
    return d

def cast_times(casts, name):
    return [e["_s"] for e in casts if e["_name"] == name]

def window_sequence(casts, center, before=4.0, after=18.0):
    """Exact ordered cast names/times around a burst anchor (for auditability)."""
    return [{"t": round(e["_s"]-center, 3), "name": e["_name"]}
            for e in casts if center-before <= e["_s"] <= center+after]

def burst_windows(casts):
    # Every Raging Strikes marks one 120s party-buff cycle. Store all three buff
    # times and an exact +/-4/+18 sec action sequence around each Raging cast.
    rs = cast_times(casts, "Raging Strikes")
    bv = cast_times(casts, "Battle Voice")
    rf = cast_times(casts, "Radiant Finale")
    out=[]
    for i,r in enumerate(rs):
        near=lambda arr: min(arr, key=lambda x:abs(x-r)) if arr else None
        b=near(bv); f=near(rf)
        out.append({"cycle": i+1, "raging_s": round(r,3),
                    "battle_voice_s": round(b,3) if b is not None else None,
                    "radiant_finale_s": round(f,3) if f is not None else None,
                    "offsets": {"battle_voice": round(b-r,3) if b is not None else None,
                                "radiant_finale": round(f-r,3) if f is not None else None},
                    "sequence": window_sequence(casts,r)})
    return out

def nearest_delta(xs, ys):
    return [min((y-x for y in ys if y>=x), default=None) for x in xs]

def parse_metrics(path):
    d=load(path); p=d["parse"]; casts=sorted(d["casts"], key=lambda e:e["timestamp"])
    duration=float(p.get("duration_s") or ((casts[-1]["_s"] if casts else 0)))
    counts=Counter(e["_name"] for e in casts)
    norm=lambda n: round(counts[n]/duration*60, 4) if duration else None
    gcd_times=sorted(e["_s"] for e in casts if e["_name"] in CORE_GCD)
    gcd_intervals=[b-a for a,b in zip(gcd_times,gcd_times[1:]) if 0 < b-a < 10]
    all_intervals=[b-a for a,b in zip([e["_s"] for e in casts],[e["_s"] for e in casts[1:]]) if 0 < b-a < 10]
    dmg=d["damage"]
    crit=sum(e.get("hitType") == 2 for e in dmg)
    dh=sum(bool(e.get("directHit")) for e in dmg)
    cd=sum(e.get("hitType") == 2 and bool(e.get("directHit")) for e in dmg)
    song_events=[]
    for n in SONGS:
        song_events += [(e["_s"],n) for e in casts if e["_name"]==n]
    song_events.sort()
    song_gaps=[b[0]-a[0] for a,b in zip(song_events,song_events[1:])]
    # <40s is a conservative event-only flag for potentially clipped/early song
    # relaunch; it is not proof that the prior song was still active.
    songs_early=sum(g < 40 for g in song_gaps)
    bw=burst_windows(casts)
    # Relationships among gauge/burst actions (nearest following action).
    rel={}
    for src,dst in [("Apex Arrow","Blast Arrow"),("Blast Arrow","Radiant Encore"),
                    ("Empyreal Arrow","Heartbreak Shot"),("Iron Jaws","Pitch Perfect")]:
        rel[f"{src}_to_{dst}_s"]=nearest_delta(cast_times(casts,src),cast_times(casts,dst))
    # Potion names are export-visible but unknown consumables may be omitted by API.
    potions=[n for n in counts if "Potion" in n or "Gemdraught" in n]
    return {
        "rank":p.get("rank"), "name":p.get("name"), "report_code":p.get("report_code"),
        "duration_s":duration, "amount":p.get("amount"), "aDPS":p.get("aDPS"), "rDPS":p.get("rDPS"),
        "raw_counts":dict(counts), "normalized_per_60s":{n:norm(n) for n in sorted(CORE | set(counts))},
        "gcd_count":sum(counts[n] for n in CORE_GCD), "cast_count":len(casts),
        "gcd_per_60s":round(sum(counts[n] for n in CORE_GCD)/duration*60,4) if duration else None,
        "casts_per_60s":round(len(casts)/duration*60,4) if duration else None,
        "gcd_interval_median_s":round(med(gcd_intervals),3) if gcd_intervals else None,
        "cast_interval_median_s":round(med(all_intervals),3) if all_intervals else None,
        "songs": {"events":[{"t":round(t,3),"name":n} for t,n in song_events],
                  "gaps_s":[round(x,3) for x in song_gaps], "gap_median_s":round(med(song_gaps),3) if song_gaps else None,
                  "gaps_lt_40s":songs_early, "casts":len(song_events)},
        "burst_windows":bw, "final_burst":bw[-1] if bw else None,
        "earlier_burst":bw[-2] if len(bw)>1 else None,
        "relationships":{k:[round(x,3) if x is not None else None for x in v] for k,v in rel.items()},
        "key_counts":{n:counts[n] for n in KEYS},
        "potion_names":{n:counts[n] for n in potions},
        "damage_events":len(dmg), "crit_events":crit, "direct_hit_events":dh, "crit_direct_events":cd,
        "crit_rate":pct(crit/len(dmg)) if dmg else None, "direct_hit_rate":pct(dh/len(dmg)) if dmg else None,
        "crit_direct_rate":pct(cd/len(dmg)) if dmg else None,
        "damage_hit_type_counts":dict(Counter(str(e.get("hitType")) for e in dmg)),
        "damage_direct_hit_counts":dict(Counter(str(bool(e.get("directHit"))) for e in dmg)),
    }

def group_summary(rows):
    def avg(field):
        xs=[r[field] for r in rows if r.get(field) is not None]
        return round(statistics.mean(xs),4) if xs else None
    def medf(field):
        xs=[r[field] for r in rows if r.get(field) is not None]
        return round(med(xs),4) if xs else None
    keys=["duration_s","amount","aDPS","rDPS","cast_count","gcd_count","casts_per_60s","gcd_per_60s",
          "gcd_interval_median_s","cast_interval_median_s","damage_events","crit_rate","direct_hit_rate","crit_direct_rate"]
    out={"n":len(rows),"averages":{k:avg(k) for k in keys},"medians":{k:medf(k) for k in keys}}
    spread_keys=["casts_per_60s","gcd_per_60s","gcd_interval_median_s","crit_rate","direct_hit_rate","crit_direct_rate"]
    out["stdevs"]={k:round(statistics.stdev([r[k] for r in rows if r.get(k) is not None]),4) if len([r[k] for r in rows if r.get(k) is not None])>1 else None for k in spread_keys}
    out["actions_per_60s"]={n:avg_nested(rows,"normalized_per_60s",n) for n in sorted(CORE)}
    out["key_counts_mean"]={n:avg_nested(rows,"key_counts",n) for n in KEYS}
    out["song_gap_median_mean_s"] = avg_nested(rows,"songs","gap_median_s")
    out["song_early_gap_rate"] = round(statistics.mean(r["songs"]["gaps_lt_40s"] / max(1,len(r["songs"]["gaps_s"])) for r in rows)*100,3) if rows else None
    out["potion_use_rate"] = round(sum(bool(r["potion_names"]) for r in rows)/len(rows)*100,3) if rows else None
    return out

def avg_nested(rows, field, key):
    xs=[]
    for r in rows:
        v=r.get(field,{})
        if isinstance(v,dict) and v.get(key) is not None: xs.append(v[key])
    return round(statistics.mean(xs),4) if xs else None

def sequence_frequencies(rows, which):
    # Keep exact sequence signatures but only surface the common signatures; event
    # ordering is more useful than a huge per-player dump in the report.
    c=Counter()
    for r in rows:
        w=r.get(which)
        if not w: continue
        sig=" > ".join(x["name"] for x in w["sequence"])
        c[sig]+=1
    return [{"parses":n,"sequence":s} for s,n in c.most_common(10)]

def burst_transition_frequencies(rows, which):
    """Most common adjacent action pairs in the exact burst windows."""
    c=Counter()
    for r in rows:
        w=r.get(which)
        if not w: continue
        names=[x["name"] for x in w["sequence"]]
        c.update(zip(names,names[1:]))
    return [{"parses":n,"from":a,"to":b} for (a,b),n in c.most_common(15)]

def main():
    paths=sorted(EVENT_DIR.glob("rank-*.json"))
    rows=[parse_metrics(p) for p in paths]
    rows.sort(key=lambda r:r["rank"])
    top=[r for r in rows if r["rank"]<=10]; low=[r for r in rows if 21<=r["rank"]<=40]
    summary={"source":"output/events/rank-01.json through rank-40.json",
             "generated_local_only":True,"n_parses":len(rows),
             "groups":{"top_10":group_summary(top),"ranks_21_40":group_summary(low)},
             "all":group_summary(rows),
             "sequences":{"top10_final":sequence_frequencies(top,"final_burst"),
                           "top10_earlier":sequence_frequencies(top,"earlier_burst"),
                           "ranks21_40_final":sequence_frequencies(low,"final_burst"),
                           "ranks21_40_earlier":sequence_frequencies(low,"earlier_burst"),
                           "transitions_top10_final":burst_transition_frequencies(top,"final_burst"),
                           "transitions_ranks21_40_final":burst_transition_frequencies(low,"final_burst")},
             "outliers":{"highest_cast_rate":sorted(rows,key=lambda r:r["casts_per_60s"] or -1,reverse=True)[:5],
                         "lowest_cast_rate":sorted(rows,key=lambda r:r["casts_per_60s"] or 999)[:5],
                         "highest_crit_rate":sorted(rows,key=lambda r:r["crit_rate"] or -1,reverse=True)[:5],
                         "lowest_crit_rate":sorted(rows,key=lambda r:r["crit_rate"] or 999)[:5]},
             "parses":rows}
    (OUT_DIR/"luna-summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    # concise report is generated from the same JSON so it remains auditable.
    def fmt(v): return "n/a" if v is None else f"{v:.3f}" if isinstance(v,float) else str(v)
    def delta(field):
        a=summary["groups"]["top_10"]["averages"].get(field); b=summary["groups"]["ranks_21_40"]["averages"].get(field)
        return (a-b if a is not None and b is not None else None)
    lines=["# Luna Bard event analysis", "",
           "Local-only analysis of 40 cached FFLogs event exports (`output/events/rank-*.json`). Kill-time files were not read or changed.", "",
           "## Executive findings", "",
           f"- Top 10 mean aDPS {fmt(summary['groups']['top_10']['averages']['aDPS'])} vs ranks 21–40 {fmt(summary['groups']['ranks_21_40']['averages']['aDPS'])}; this is a result-grouping association, not a causal estimate.",
           f"- Top 10 mean cast rate {fmt(summary['groups']['top_10']['averages']['casts_per_60s'])}/min vs {fmt(summary['groups']['ranks_21_40']['averages']['casts_per_60s'])}/min; mean GCD rate {fmt(summary['groups']['top_10']['averages']['gcd_per_60s'])}/min vs {fmt(summary['groups']['ranks_21_40']['averages']['gcd_per_60s'])}/min.",
           f"- Mean event-level crit rate is {fmt(summary['groups']['top_10']['averages']['crit_rate'])}% (top 10) vs {fmt(summary['groups']['ranks_21_40']['averages']['crit_rate'])}% (21–40); direct-hit rate is {fmt(summary['groups']['top_10']['averages']['direct_hit_rate'])}% vs {fmt(summary['groups']['ranks_21_40']['averages']['direct_hit_rate'])}%. These are RNG-sensitive damage-event proportions.",
           f"- Song relaunch gaps average median {fmt(summary['groups']['top_10']['averages']['songs' ] if False else summary['groups']['top_10'].get('song_gap_median_mean_s'))} s (top 10) vs {fmt(summary['groups']['ranks_21_40'].get('song_gap_median_mean_s'))} s; gaps under 40 s are only a screening flag for possible clipping.", "",
           "## Core action rates (mean casts per 60 seconds)", "",
           "| Action | Top 10 | Ranks 21–40 | Difference |", "|---|---:|---:|---:|"]
    for n in ["Burst Shot","Refulgent Arrow","Heartbreak Shot","Empyreal Arrow","Iron Jaws","Pitch Perfect","Apex Arrow","Blast Arrow","Radiant Encore","Sidewinder"]:
        a=summary['groups']['top_10']['actions_per_60s'].get(n); b=summary['groups']['ranks_21_40']['actions_per_60s'].get(n)
        lines.append(f"| {n} | {fmt(a)} | {fmt(b)} | {fmt(a-b if a is not None and b is not None else None)} |")
    lines += ["", "## Burst execution and exact sequences", "",
              "Each parse has five Raging Strikes/Battle Voice/Radiant Finale cycles in the exported casts (a final partial cycle may exist for very short parses). The JSON preserves exact ordered casts and offsets in a ±4/18-second window around each Raging Strikes cast; `final_burst` and `earlier_burst` are the last and penultimate cycles.", "",
              "Common final-cycle signatures (top 10):"]
    for x in summary['sequences']['top10_final'][:5]: lines.append(f"- {x['parses']} parses: `{x['sequence']}`")
    lines += ["", "Common final-cycle signatures (ranks 21–40):"]
    for x in summary['sequences']['ranks21_40_final'][:5]: lines.append(f"- {x['parses']} parses: `{x['sequence']}`")
    lines += ["", "Observed robust pattern: every cached parse has five Raging Strikes, five Battle Voice, and five Radiant Finale casts. Barrage has one four-cast outlier; exact weave order and late-fight truncation should be judged from per-parse JSON rather than a single canonical sequence.", "",
              "## Songs, key procs, and outliers", "",
              f"- Song casts average {fmt(statistics.mean(r['songs']['casts'] for r in top))} per top-10 parse vs {fmt(statistics.mean(r['songs']['casts'] for r in low))} for ranks 21–40. Under-40-second adjacent-song gaps: {fmt(summary['groups']['top_10'].get('song_early_gap_rate'))}% top 10 vs {fmt(summary['groups']['ranks_21_40'].get('song_early_gap_rate'))}% ranks 21–40.",
              f"- In the exact final-burst windows, the most common adjacent transitions are `{summary['sequences']['transitions_top10_final'][0]['from']} → {summary['sequences']['transitions_top10_final'][0]['to']}` ({summary['sequences']['transitions_top10_final'][0]['parses']} occurrences) for top 10 and `{summary['sequences']['transitions_ranks21_40_final'][0]['from']} → {summary['sequences']['transitions_ranks21_40_final'][0]['to']}` ({summary['sequences']['transitions_ranks21_40_final'][0]['parses']}) for ranks 21–40; no single full sequence recurs across these 40 exports.",
              "- Apex Arrow, Blast Arrow, and Radiant Encore counts plus nearest-following timing are preserved per parse; compare `key_counts` and `relationships` to study gauge/proc conversion. Event exports do not include gauge values, so missed-opportunity claims are hypotheses.",
              "- Empyreal Arrow, Heartbreak Shot, Iron Jaws, and Pitch Perfect counts/rates are similarly observable. Pitch Perfect count is not a direct measure of repertoire stacks because stacks are not exported.",
              "- Potion events are identifiable when the ability name is exported (mostly `Grade 4 Gemdraught of Dexterity [HQ]`); absence is not proof of no potion because API/event filtering can omit actions.",
              f"- Rate outliers are preserved in `outliers`: highest cast-rate parse is rank {summary['outliers']['highest_cast_rate'][0]['rank']} ({fmt(summary['outliers']['highest_cast_rate'][0]['casts_per_60s'])}/min), lowest is rank {summary['outliers']['lowest_cast_rate'][0]['rank']} ({fmt(summary['outliers']['lowest_cast_rate'][0]['casts_per_60s'])}/min); highest and lowest event-level crit-rate parses are ranks {summary['outliers']['highest_crit_rate'][0]['rank']} ({fmt(summary['outliers']['highest_crit_rate'][0]['crit_rate'])}%) and {summary['outliers']['lowest_crit_rate'][0]['rank']} ({fmt(summary['outliers']['lowest_crit_rate'][0]['crit_rate'])}%).",
              "- The clearest group-level association is slightly higher top-10 GCD rate and crit rate, while total cast rate is virtually identical. That is descriptive; the event export cannot establish whether damage, execution, encounter uptime, or RNG caused rank differences.", "",
              "## RNG and limitations", "",
              "- Crit/direct-hit percentages use all exported damage events, including periodic ticks and multi-hit effects; they are not weighted contribution rates. `hitType==2` is treated as critical and the export's `directHit` flag as direct hit.",
              "- Timing is relative to each export's first cast. Cast events show intent/order, not animation-lock completion, slidecast, missed targets, server latency, or exact GCD readiness.",
              "- No gauge/resource state, buff snapshots, party composition, deaths/mechanics, or target uptime is present in these files. Therefore the report distinguishes descriptive recurring patterns from optimization hypotheses.",
              "- Full per-parse details, exact final/earlier sequences, all action counts, damage-event RNG, and outlier identification are in `luna-summary.json`.", ""]
    (OUT_DIR/"luna-report.md").write_text("\n".join(lines))
    print(f"wrote {OUT_DIR/'luna-report.md'} and {OUT_DIR/'luna-summary.json'}")

if __name__ == "__main__": main()
