# CielBard simulator: findings and decisions

- **2026-09-18. Measured with sim 1.0.0 driving engine 0.5.2 unmodified**, on the corrected
  Patch 7.5 potency tables (Apex Arrow 140 at 20 gauge to 700 at 100, Blast Arrow 700 with
  50% falloff, Resonant Arrow 640 with 50% falloff, Refulgent Arrow 280 and 840 under
  Barrage, Shadowbite 200 and 300 under Barrage, Wide Volley 140 / 220, Ladonsbite 140,
  Radiant Encore 700 / 800 / 1100, Heavy Shot 160). `tests/test_integration.py` pins the
  shipped Lua by sha256; nothing under `CielBard/` was modified by this pass.
- **The 0.5.1 engine changes this document recommended WERE applied, and the 0.5.2 changes
  the code review recommended WERE applied.** Sections 1-3 record what was measured before
  them; section 4 records the re-run on the corrected data. Where an old number and a new
  number disagree, the new one wins.
- All DPS on the refitted scale `potency_to_damage = 128.559424`
  (`sim/output/stats.override.json`; `sim/data/stats.json` still ships the uncalibrated
  100.0). The scalar is an exact linear multiplier, so every percentage, sigma and p-value
  here is identical at any scale.
- Suites green: `tests/run_sim_tests.py` (217 tests, 2 documented `expectedFailure`),
  `tests/run_mock_tests.py`, `tests/run_gui_tests.py`.
- Sources: `sim/output/calibration.md` (re-run this pass, 150 seeds per duration anchor),
  `sim/output/sweep_apex.md` (re-run this pass, 300 paired seeds per point),
  `sim/output/empyreal_report.md` and `sim/output/pp_ironjaws_report.md` (0.5.0, still
  carrying their staleness banners: the diagnoses stand and their fixes shipped, but their
  DPS numbers were taken on the old potency curve).

**The decision in one paragraph.** Everything this document recommended has shipped. Under
the corrected potencies the engine simulates **1.37% below the top-10 parse mean** at its
current defaults, and the rotation-shape agreement that a scalar cannot fake improved
sharply: the Empyreal Arrow count gap closed from -12.1% to **-0.3%** and Iron Jaws from
-5.8% to **+2.7%**. Two settings questions that the potency correction re-opened are now
answered: **`apexOffcycleGauge = 80` is confirmed** (+0.237% over 90, p = 0.000079) and
**`chargePoolSeconds = 25` should stay** (every alternative loses). One recommendation is
new and weak: **`apexHoldForBurstSeconds` 35 -> 0**, +0.128% at p = 0.0524. The simulator
now has a multi-target damage model, and it confirms the review's Barrage/Shadowbite
arithmetic in the engine's own casts.

---

## 1. What the mechanics corrections changed (0.5.0, historical)

The mechanics-corrections pass modelled Barrage's triple hit (`statuses.json`
`weaponskill_hits = 3`, spent on the next `multi_hit_eligible` weaponskill, so the
Refulgent Arrow after a Barrage is worth 840 instead of 280) and added override validation
to the simulator.

**In DPS: the level moved, the fit did not get better or worse.**

| quantity | before | after |
|---|---:|---:|
| fitted `potency_to_damage` | 136.7979 | **132.4016** |
| implied simulated potency output | - | **+3.3 %** |
| residual mean abs / max over the 40 parses | 0.99 % / 2.78 % | 0.99 % / 2.73 % |
| model R^2 against the constant-mean null | 0.0326 | 0.0294 |
| sim DPS at 510 s, no kill window, 150 seeds | - | 34,171.4 +/- 45.0 |
| gap to the top-10 parse mean (34,633.4) | -1.39 % | **-1.33 %** |

**In rates: nothing moved.** Every per-action rate at 520 s changed by under 1 %. That is
the result you want from a damage-table correction - it changed what a cast is worth, not
what the engine casts. The same is true of the Patch 7.5 correction in section 4.

`Simulation._apply_job_overrides` now validates `FightConfig.job_overrides` against
`job.json` and re-runs `sim.tables._validate_job` on the merged table. Before it, a
misspelled override was accepted silently, left the default in place, and reported a clean
run that had tested nothing - and two of the three investigations below steer the simulator
entirely through overrides.

**Kill-time bands, 120 seeds per band** (`killband.csv`, `killband_nokill.csv`), on the old
curve:

| band | parses | real mean aDPS | sim fight | sim DPS, kill window on | err % | kill window off | cost of the window |
|---|---:|---:|---:|---:|---:|---:|---:|
| <20 s | 14 | 33,927.7 | 494 s | 33,493.7 +/- 53.0 | -1.28 | 33,450.5 | **+43.2** |
| 20-30 s | 13 | 34,240.3 | 507 s | 33,830.2 +/- 50.6 | -1.20 | 34,054.3 | -224.1 |
| 31-60 s | 10 | 34,161.9 | 527 s | 33,989.4 +/- 49.8 | -0.51 | 34,066.7 | -77.3 |
| >60 s | 3 | 33,782.6 | 552 s | 33,766.9 +/- 47.6 | -0.05 | 33,818.2 | -51.3 |

Real spread across bands 457.7 DPS (1.35 %), simulated 495.7 (1.48 %) - the same magnitude.
The shape still disagrees in one place: the real peak is `20-30 s` and the simulator's is
`31-60 s`. That disagreement is unresolved and has not been re-measured on the new curve.

---

## 2. The Apex sweep (0.5.0, superseded by section 4.2)

At 300 paired seeds on the old 100-600 curve against engine 0.5.0, gauge 80 with no hold
beat the then-shipped 90 / 35 by **+86.7 DPS, +0.254 %** (t(299) = +3.67, p = 0.0003,
CI +0.12 % to +0.39 %); the gauge carried the whole effect (80 vs 90 was +0.198 % at hold 0
and +0.225 % at hold 35), the hold was worth nothing measurable, and gauge 100 was the worst
of the three at -0.299 %. 0.5.1 shipped `apexOffcycleGauge = 80` on that evidence.

Two structural findings from that run still hold:

1. **`apexHoldForBurstSeconds` is unreachable at gauge 100.** `CielBard_Rotation.lua` gates
   the hold on `ctx.soulVoice < 95`, so every gauge-100 row is bit-identical regardless of
   the hold. Any sweep crossing gauge > 95 with a hold axis wastes those points.
2. **Soul Voice overcap is not the mechanism.** It is exactly 0 at gauge 80 and 90 and about
   2.4-2.7 per fight at gauge 100 - 0.3 % of the roughly 800 gauge a fight spends. What
   gauge 100 costs is Apex+Blast pairs, not overcap.

**Section 4.2 supersedes the DPS numbers here.** They were taken on a curve where an
80-gauge Apex was worth 475; it is now worth 560.

---

## 3. Diagnoses and the engine changes they produced (0.5.0 measurements, all shipped)

### 3.1 Empyreal Arrow, -12.1 %: one predicate, one lost cast per burst window

Full report: `sim/output/empyreal_report.md`.

**It was not weave congestion.** Over 510 s, Empyreal sat ready-but-uncast for **61.91 s =
4.13 lost recasts** (30.00 casts of a possible 34). Attribution, seeds 1-10:

| gate | s/fight | share |
|---|---:|---:|
| `holdEmpyreal` (`CielBard_Rotation.lua:958`) | **42.57** | **68.8 %** |
| animation lock, in burst | 14.39 | 23.2 % |
| clip guard `weaveMinGcdRemaining`, in burst | 3.39 | 5.5 % |
| animation lock, opener | 0.63 | 1.0 % |
| GCD window / `maxWeaves` / another oGCD took the slot | 0.90 | 1.5 % |
| `requestThrottleMs` / engine pulse cadence | **0.00** | **0.0 %** |

**Root cause.** The nominal 5 s hold was really ~15 s, because `nextBurstSeconds()` returned
0 on the *first* ready burst action and Radiant Finale's 110 s recast comes up ~7.5 s before
Raging Strikes' 120 s. Fifteen seconds is exactly one Empyreal recast. **Isolation proof:**
disabling only Radiant Finale, with the hold rule fully in place, dropped the hold from
42.16 s to **1.33 s** and raised Empyreal from 30.00 to **33.67**.

**Measured value of removing the hold:** +253.7 DPS (+0.75 %) unpaired at 150 seeds,
+225.8 (+0.67 %, t = +3.53) at 60 paired seeds, +187.3 (+0.55 %, t = +2.81) at 60 ms ping.
**All of it was the Empyreal hold**, not the other two things `resourcePooling` governs.

**Shipped in 0.5.1** as the maximum form of `nextBurstSeconds()` plus a new
`empyrealHoldForBurstSeconds = 0`. **Confirmed by the 0.5.2 calibration:** Empyreal is now
3.923/min against the parses' 3.937, a -0.3 % gap where it was -12.1 %.

### 3.2 Pitch Perfect, -4.8 %: not a defect

Full report: `sim/output/pp_ironjaws_report.md`.

The stack budget balances exactly over 40 seeds: income 64.375 Repertoire procs inside
Wanderer's Minuet (50.375 song-timer + 14.000 Empyreal), 62.825 spent, **0.475 lost to the
3-stack cap** (0.7 % of income, 57 potency), **0.000 lost at song end**. The gap's sign
depends on the kill window: with `--kill-time 510` the engine casts **3.062/min, 8.8 %
*above* the top-10 2.814**, because the terminal band dumps at one stack. The calibration's
-4.8 % (now -5.6 %) is `sim.calibrate` not setting `kill_time_s`.

**No Lua change was warranted and none was made.**

### 3.3 Iron Jaws, -5.8 %: a real defect with no measurable DPS cost

**Cause was priority, not the threshold.** Blast Arrow, Resonant Arrow, Radiant Encore and
Apex Arrow all preceded the DoT refresh, and `dotRefreshSeconds = 3.0` is 1.2 GCDs at the
simulated 2.37 s GCD. 1.450 DoT fall-off events per fight; blockers per fight Blast 0.625,
Resonant 0.550, Apex 0.400, Encore 0.375 - chains up to two consumers deep.

Fall-off events vs `dotRefreshSeconds`, 40 seeds: 3 s -> 1.450, 6 s -> **0.300**. Raising
the threshold was nevertheless the wrong fix: it discards 30-47 seconds of DoT duration per
fight, which is why its DPS was flat. **No config knob moved DPS**; the fix had to be a
priority change.

**Shipped in 0.5.1** as an urgency pre-empt with `dotUrgentSeconds = 1.5` ahead of the
proc-consumers. **Confirmed by the 0.5.2 calibration:** Iron Jaws is now 1.343/min against
the parses' 1.308 (+2.7 %, from -5.8 %), and 11.60 casts per 510 s fight against 10.70.

### 3.4 Status of the ranked change list

| # | change | expected then | status |
|---:|---|---:|---|
| 1 | `nextBurstSeconds()` -> max over enabled burst actions, plus `empyrealHoldForBurstSeconds = 0` | +0.67 % to +0.75 % | **Shipped 0.5.1.** Confirmed on counts by the 0.5.2 calibration |
| 2 | `apexOffcycleGauge` 90 -> 80 | +0.25 % | **Shipped 0.5.1.** Re-confirmed at +0.237 % on the corrected curve (4.2) |
| 3 | Iron Jaws urgency pre-empt, `dotUrgentSeconds = 1.5` | +0.16 % (estimated) | **Shipped 0.5.1.** Confirmed on counts by the 0.5.2 calibration |
| 4 | Terminal-window policy (`terminalTTK` / `idealKillMax` / `terminalDumping`) | +0.31 % observed, confounded | **Not made.** Still confounded - the axis governs three behaviours at once. Not re-measured |
| 5 | Remove `apexHoldForBurstSeconds` | 0.00 % | **Not made.** Now reads +0.128 % at p = 0.0524 (4.2); recommended as a default change, still not proven |
| - | Pitch Perfect | no change | **No change made.** Correct |

**Explicitly still not recommended:** `maxWeaves = 3` (bit-identical to no change at 60 ms
ping - a zero-ping artefact); re-ordering the burst priority list; lowering
`weaveMinGcdRemaining`, `requestThrottleMs` or `pulseMs`; raising `dotRefreshSeconds` to 6
or 7.

---

## 4. The 0.5.2 re-run on Patch 7.5 potencies

### 4.1 Calibration

`sim.calibrate`, **seeds 1-150 at each of the five duration anchors** (502 / 510 / 520 /
532 / 550 s), 40 parses from `bard-analysis/output/killtime/killtime.csv`. Full report:
`sim/output/calibration.md`.

| quantity | 0.5.0, old potencies | **0.5.2, corrected** |
|---|---:|---:|
| fitted `potency_to_damage` | 132.4016 | **128.5594** |
| implied extra simulated potency | - | **+3.0 %** |
| residual mean abs / max over the 40 parses | 0.99 % / 2.73 % | **0.98 % / 2.85 %** |
| model R^2 against the constant-mean null | 0.0294 | 0.0377 |
| fitted sim DPS spread (sd) | 107.1 | 77.8 |
| realized crit / DH (report 25.366 / 28.587) | 25.47 / 28.84 | 25.46 / 28.74 |

The scalar is fitted as `sum(aDPS) / sum(sim DPS)`, so the mean residual is zero by
construction and the residual columns measure parse-to-parse scatter, not model accuracy.
132.4016 / 128.5594 = 1.0299 is the potency the corrections added. **Judge the rotation from
the rate table, never from the DPS number.**

**The rate table is where the 0.5.1 changes show up**, casts per minute at the 520 s anchor:

| action /min | 0.5.0 | **0.5.2** | top-10 | 0.5.0 delta | **0.5.2 delta** |
|---|---:|---:|---:|---:|---:|
| Empyreal Arrow | 3.462 | **3.923** | 3.937 | -12.1 % | **-0.3 %** |
| Iron Jaws | 1.232 | **1.343** | 1.308 | -5.8 % | **+2.7 %** |
| charge spenders (combined) | 7.292 | **7.427** | 7.384 | -1.3 % | **+0.6 %** |
| Barrage / Battle Voice / Finale / Raging / Encore | 0.577 | 0.577 | 0.579 | -0.3 % | -0.3 % |
| Pitch Perfect | 2.678 | 2.655 | 2.814 | -4.8 % | -5.6 % |
| Apex Arrow | 0.959 | **1.065** | 0.973 | -1.4 % | **+9.5 %** |
| Blast Arrow | 0.956 | **1.061** | 0.949 | +0.7 % | **+11.7 %** |
| all casts | 43.071 | 43.623 | 45.270 | -4.9 % | -3.6 % |
| GCDs | 25.255 | 25.239 | 25.311 | -0.2 % | -0.3 % |

Three of the four count gaps that opened these investigations are closed. The remaining
Pitch Perfect gap is the known `sim.calibrate` artefact (section 3.2). The residual -3.6 %
on all casts is the unmodelled utility casts (Warden's Paean, Troubadour, Nature's Minne,
Repelling Shot).

**The Apex/Blast overshoot is new and is a consequence of `apexOffcycleGauge = 80`, not of
the potency correction.** It is discussed in 4.2 and it is the sharpest surviving test of
the Repertoire proc model (section 5).

At the current defaults the engine simulates **34,158.9 +/- 34.0 DPS** at 510 s with no kill
window over 300 seeds, **1.37 % below the top-10 mean aDPS of 34,633.4**.

### 4.2 The Apex sweep, re-run: 80 still beats 90

Full report: `sim/output/sweep_apex.md`. `apexOffcycleGauge` {80, 90, 100} x
`apexHoldForBurstSeconds` {0, 35}, **300 paired seeds per point, 1800 fights**, 510 s,
ping 0, pulse 30 ms, single target, no downtime, no potion, no kill time. 0 rejections,
0 engine warnings.

| gauge / hold | n | DPS mean | sem | Apex | Blast | Apex /min | SV overcap | potency |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **80 / 0 (recommended)** | 300 | **34,202.7** | 32.2 | 9.57 | 9.53 | 1.126 | 0.00 | 102,350 |
| 100 / 0 | 300 | 34,168.6 | 31.7 | 7.96 | 7.96 | 0.936 | 2.65 | 102,129 |
| 100 / 35 | 300 | 34,168.6 | 31.7 | 7.96 | 7.96 | 0.936 | 2.65 | 102,129 |
| **80 / 35 (shipped)** | 300 | 34,158.9 | 34.0 | 9.07 | 9.03 | 1.067 | 0.00 | 102,283 |
| 90 / 0 | 300 | 34,121.6 | 33.3 | 8.64 | 8.60 | 1.016 | 0.00 | 102,232 |
| 90 / 35 (pre-0.5.1) | 300 | 34,113.8 | 33.7 | 8.41 | 8.37 | 0.990 | 0.00 | 102,209 |

| paired comparison | diff | % | t(299) | p | 95 % CI |
|---|---:|---:|---:|---:|---|
| **80 / 0 vs 90 / 0** | **+81.0** | **+0.237** | **+4.00** | **0.000079** | **+0.121 % to +0.354 %** |
| **80 / 0 vs 90 / 35** | **+88.9** | **+0.260** | **+4.21** | **0.000034** | **+0.139 % to +0.382 %** |
| 80 / 35 vs 90 / 35 | +45.1 | +0.132 | +2.19 | 0.0292 | +0.014 % to +0.251 % |
| **80 / 0 vs 80 / 35** | +43.7 | +0.128 | +1.95 | **0.0524** | -0.001 % to +0.257 % |
| 90 / 0 vs 90 / 35 | +7.8 | +0.023 | +0.47 | 0.6416 | -0.074 % to +0.120 % |
| 100 / 0 vs 90 / 0 | +46.9 | +0.138 | +1.99 | 0.0480 | +0.001 % to +0.274 % |
| 80 / 0 vs 100 / 0 | +34.1 | +0.100 | +1.42 | 0.1558 | -0.038 % to +0.238 % |

**Answer to the review's question: yes, 80 still beats 90 under the 140-700 curve, and by
more than before.** The old curve made an 80-gauge Apex worth 79.2 % of a full one
(475 / 600); the corrected curve makes it 80.0 % (560 / 700), so firing early costs
relatively less and the margin widened from +0.198 % to +0.237 % at hold 0.

**Two things did change.** Gauge 100 is no longer the worst point - it is second, not
separable from 80 (p = 0.156), and ahead of 90 (p = 0.048); **gauge 90 is now the worst of
the three**. And the hold, which measured exactly nothing before, now reads +0.128 % at
gauge 80 - positive, but at p = 0.0524, which is not a result. Resolving a 0.128 % effect at
80 % power needs about 590 seeds per point; that run has not been made.

### 4.3 The charge-pool sweep, re-run with `nextBurstSeconds()` unskewed

`chargePoolSeconds` {0, 15, 25, 35}, 300 paired seeds, 510 s, same conditions as 4.2.
Baseline is the shipped 25.

| chargePoolSeconds | n | DPS mean | sem | Heartbreak Shot | vs 25 | % | t(299) | p |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **25 (shipped)** | 300 | **34,158.9** | 34.0 | 63.79 | - | - | - | - |
| 35 | 300 | 34,131.9 | 33.6 | 62.81 | -27.0 | -0.079 | -0.89 | 0.3727 |
| 15 | 300 | 34,110.2 | 37.2 | 63.90 | -48.7 | -0.143 | -2.33 | 0.0203 |
| 0 | 300 | 34,099.9 | 36.7 | 63.90 | -59.0 | -0.173 | -2.13 | 0.0340 |

**Verdict: keep `chargePoolSeconds = 25`. No change recommended.** It is the best of the
four, and the two points that lose significantly are the ones that pool *less*, not more -
the shared charge pool is worth more inside the burst than ahead of it.

**The skew fix is visible exactly where it was predicted.** On engine 0.5.0,
`chargePoolSeconds = 35` collapsed: it lost **5.6 Heartbreak casts** (63.16 -> 57.54) and
-281 DPS at 3.3 sigma, because `nextBurstSeconds()` returned ~7.5 s early and turned a 35 s
window into ~42 s, which outran the 15 s recharge (the 0.5.0 revision of `sweep_chargepool.csv`, 100 seeds). With the maximum
form it loses **0.98 casts** (63.79 -> 62.81) and -27 DPS at p = 0.37. The pathology is
gone; 35 is now merely slightly worse than 25 rather than badly broken.

### 4.4 Multi-target: the review's Barrage arithmetic, in the engine's own casts

The simulator now has a multi-target damage model (Ladonsbite, Shadowbite and Rain of Death
hit every clustered target with no falloff; Blast Arrow, Resonant Arrow and Radiant Encore
take the 50 % falloff after the first), so replacement thresholds can be measured rather
than argued. Three 300-seed batches at 300 s, shipped defaults, every enemy inside the
5 yalm cluster radius:

| per fight | 1 target | 2 targets | 3 targets |
|---|---:|---:|---:|
| **Shadowbite** | 0.00 | **27.08** | **29.92** |
| **Refulgent Arrow** | **29.92** | **2.85** | **0.00** |
| **Ladonsbite** | 0.00 | **71.50** | **71.50** |
| **Rain of Death** | 0.00 | **37.72** | **37.72** |
| Burst Shot | 71.50 | 0.00 | 0.00 |
| Heartbreak Shot | 37.72 | 0.00 | 0.00 |
| Barrage | 3.00 | 3.00 | 3.00 |
| Barrages that expired unused | 0.15 | 0.15 | 0.15 |
| Apex / Blast / Resonant / Encore | 5.18 / 5.11 / 3.00 / 3.00 | same | same |
| Empyreal / Pitch Perfect / Iron Jaws | 20.00 / 15.17 / 5.87 | same | same |
| GCDs | 125.85 | 125.85 | 125.85 |
| DPS (sem) | 34,510 (43) | 43,223 (53) | 58,033 (61) |

**`REVIEW_0.5.1.md` High #2 is fixed, and the fix is exactly the size it should be.** At two
targets the engine casts Refulgent Arrow **2.85** times per fight and Shadowbite 27.08; at
three targets Refulgent falls to **0.00** and Shadowbite rises by **2.84** to 29.92. Every
other count is identical between the two batches, and so is the GCD count. There were 3.00
Barrages per fight and 0.15 expired unused, so **2.85 is precisely the number of
Barrage-enhanced Hawk's Eye procs**: at two targets every one of them goes to Refulgent
Arrow (280 x 3 = 840) instead of Shadowbite (300 x 2 = 600), and at three targets every one
goes to Shadowbite (300 x 3 = 900) instead of Refulgent (840). That is the whole of the
review's arithmetic, executed by the shipped engine, with no other behaviour disturbed.

Ordinary Hawk's Eye procs still go to Shadowbite at two targets, which is correct
(200 x 2 = 400 against Refulgent's 280). The Hawk's Eye proc budget itself does not move
with target count: 29.92 procs consumed per fight at one target, 29.93 at two.

The other two AoE replacements substitute cleanly at two targets and disturb nothing else:
Ladonsbite 71.50 takes over the entire Burst Shot slot (140 x 2 = 280 against 220) and Rain
of Death 37.72 takes over the entire Heartbreak Shot slot (100 x 2 = 200 against 180).

**What the batches do not show.** Every target has the primary's health and lifetime, they
all stand inside the cluster radius, and none of them dies. That is the right shape for
testing a *replacement threshold* and the wrong shape for testing `multiDot`, which the
review disabled by default (High #3) for exactly the reason this model cannot yet answer:
whether a secondary target lives long enough to pay back the DoT GCDs. **`multiDot = false`
should stay until per-target time-to-kill exists in both the engine and the simulator.**
The 2- and 3-target DPS figures above are the ceiling of a perfectly clustered, equally
durable pack, not a trash pull.

### 4.5 Recommended defaults after this pass

| setting | shipped 0.5.2 | recommended | evidence |
|---|---|---|---|
| `apexOffcycleGauge` | 80 | **80, unchanged** | +0.237 % over 90, p = 0.000079, CI +0.121 % to +0.354 % (4.2) |
| `apexHoldForBurstSeconds` | 35 | **0** | +0.128 % at gauge 80, p = 0.0524 - a recommendation on sign and simplicity, not a significant result (4.2) |
| `chargePoolSeconds` | 25 | **25, unchanged** | best of {0, 15, 25, 35}; 0 and 15 lose significantly (4.3) |
| `empyrealHoldForBurstSeconds` | 0 | **0, unchanged** | Empyreal count gap closed to -0.3 % (4.1) |
| `dotUrgentSeconds` | 1.5 | **1.5, unchanged** | Iron Jaws count gap closed to +2.7 % (4.1) |
| `aoeTargets.Ladonsbite` | 2 | **2, unchanged** | 140 x 2 = 280 > 220 (4.4) |
| `aoeTargets.Shadowbite` | 2 | **2, unchanged** | 200 x 2 = 400 > 280 (4.4) |
| `aoeTargets.ShadowbiteBarrage` | 3 | **3, unchanged** | confirmed in casts: 2.85 Barrage procs reroute at exactly the right target count (4.4) |
| `aoeTargets.RainOfDeath` | 2 | **2, unchanged** | 100 x 2 = 200 > 180 (4.4) |
| `multiDot` | false | **false, unchanged** | no per-target TTK model exists in either engine or simulator (4.4) |

**Only one change is recommended, and it is a weak one.** Nothing under `CielBard/` was
modified by this pass; `apexHoldForBurstSeconds` is left for the maintainer to decide.

---

## 5. Remaining unverified assumptions

Ordered by how much of the above rests on them. The full list, in the simulator's own words,
is under "Unverified assumptions" in `sim/output/calibration.md` and in `sim/README.md`.

**Load-bearing for a conclusion here:**

1. **The Repertoire proc model** (corrections item 1: 80 % every 3 s on the song timer from
   42 s remaining down to 3 s, none in the final 3 s, and independent of DoT presence -
   `job.repertoire_independent_of_dots`, default `true`). **This is the sharpest open
   question in the simulator.** The top-10 parses run 0.973 Apex/min. On engine 0.5.2 the
   shipped gauge 80 produces **1.126/min, 16 % above** the parse rate, while gauge 90
   produces 0.990/min and lands on it. Either the top 10 were not firing at 80, or this
   model overstates gauge income by 12-14 %. `MECHANICS_CORRECTIONS.md` item 18 says the
   surviving event exports cannot decide it. The DPS comparison in 4.2 is within-model and a
   uniform income error cancels out of it; the *rate* agreement that would independently
   corroborate gauge 80 does not. Worth its own investigation - flip
   `repertoire_independent_of_dots` to `false` and re-run the Apex grid.
2. **Apex Arrow's potency floor**: 140 at 20 gauge, linear to 700 at 100. Only the 700
   endpoint is documented. The whole 80-vs-90 result is a trade between cast count and curve
   value, and the last correction to this curve moved gauge 100 from worst to second - a
   differently-shaped floor could move it again.
3. **The 0.6 s oGCD animation lock.** Measured MMOMinion gaps in `HANDOFF.md` were
   640-719 ms including client overhead, so the 23 % of Empyreal drift charged to animation
   lock is a lower bound.
4. **The linear dummy HP model** (`hp% = 100 * (1 - t / seconds)`) drives the engine's TTK
   bands under `--kill-time`, and therefore every kill-window number in section 1 and the
   whole `terminalDumping` lead in item 4 of the 3.4 ranking.
5. **The multi-target geometry model.** Section 4.4 assumes every extra enemy is inside the
   5 yalm cluster radius, has the primary's HP, and never dies. The replacement-threshold
   result does not depend on it - the batches differ only in the target count the engine
   reads - but the DPS figures do.

**Flagged, not load-bearing here:**

- Army's Muse / Army's Ethos haste table (1 / 2 / 4 / 12 % by stacks, 30 s Ethos carry-over)
  - simulator model, not in any source.
- Barrage's model: `weaponskill_hits = 3` spent on the next `multi_hit_eligible` weaponskill
  (Refulgent Arrow only), with the AoE Hawk's Eye weaponskills taking a flat potency
  increase instead (Shadowbite 200 -> 300, Wide Volley 140 -> 220). The 3.0 % scalar move
  rests on the eligibility list being right; the rates do not.
- Barrage's Hawk's Eye guaranteed while every other source rolls 35 %
  (`job.hawks_eye_proc_chance`) - the *scope* of that one knob is the assumption.
- Radiant Encore 700 / 800 / 1100 by coda count - the official job guide value, confirmed
  current this pass, against Icy Veins' 500 / 600 / 900.
- 30 s Barrage / Radiant Finale transform windows; the 10 s Barrage buff; 20 s Battle Voice,
  Radiant Finale and Raging Strikes - from the guides, not measured on the client.
- Non-DoT status ids are internal to the simulator: self-consistent, unverified against the
  live client.
- Base crit / DH are the merged report's top-10 *event* rates (25.366 % / 28.587 %) with the
  simulator's own buff uptimes deconvolved out; they are not damage-weighted.
- Bloodletter's 130 potency is kept in the tables although the action is trait-upgraded to
  Heartbreak Shot (180) at level 100. Heavy Shot (160) and Quick Nock (110) are likewise
  level-sync fallbacks never expected at 100.

**Structural limits, not assumptions:**

- **Stationary, no downtime, ping 0** for every DPS number above except the 60 ms Empyreal
  re-run. Utility casts are not modelled, which is most of the residual 3.6 % cast gap.
- **The scalar absorbs what it should not**: external raid buffs in aDPS, the parses'
  movement and downtime, the potion (measured +1.08 % at 150 seeds, 5.7 sigma), and Bard
  auto attacks (`stats.auto_attack_dps` ships at 0.0, worth 7-10 % of real aDPS, and
  absorbed as a multiple of potency rather than of time - which biases any experiment that
  moves GCD count or uptime without moving potency).
- **One multiplicative scalar cannot correct a rotation-shape error.** Its mean residual is
  zero by construction and its R^2 against a constant-mean null is 0.038.
- **Two SPEC scenarios are unreachable by the shipped engine** and are documented rather
  than papered over (the 150 ms ping oGCD reduction, arithmetically impossible below
  ~350 ms; the potion landing before Raging Strikes on the opener). Their tests are
  `expectedFailure`, so an engine change that satisfies them fails the suite loudly.
- **The live-client request race is invisible here.** The simulator flips readiness the
  instant a request is accepted, so the `requestDedupeMs` guard 0.5.2 added cannot be
  exercised by any simulated fight. It has a mocked-runtime test instead.
