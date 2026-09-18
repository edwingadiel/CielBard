# CielBard sim calibration

- generated: 2026-09-18T06:57:44Z
- sim 1.0.0, engine 0.5.2, seeds 1-150, pulse 30ms, ping 0ms
- source: bard-analysis/output/killtime/killtime.csv (40 parses, 496.1-568.6s)
- fitted potency_to_damage: 128.5594 (from 100.0, x1.285594)
- least-squares ratio: 128.5594
- residual: mean absolute error 0.98%, max 2.85%
- constant-mean null: mean absolute error 1.02%, max 3.00%; model R^2 against it 0.0377
- spread: actual aDPS mean 34076.9 sd 411.8; fitted sim DPS sd 77.8
- realized rates: crit 25.46% (report 25.366%), dh 28.74% (report 28.587%)

The scalar is fitted as sum(aDPS) / sum(sim DPS), so the mean residual is zero by construction and the residual tables below measure parse-to-parse scatter, not model accuracy. A one-parameter multiplicative fit constrains the DPS level only and carries no information about rotation shape: when the model's error columns match the constant-mean null's, the fit has explained nothing beyond the level. Judge the rotation from the per-action rate table instead.

## Fit by fight length

| duration_s | parses | mean actual aDPS | sim DPS (fitted) | ratio | err % |
|---:|---:|---:|---:|---:|---:|
| 502.0 | 8 | 33928.0 | 34069.0 | 1.0042 | 0.42 |
| 510.0 | 18 | 34165.5 | 34129.9 | 0.9990 | -0.10 |
| 520.0 | 5 | 34123.7 | 34087.0 | 0.9989 | -0.11 |
| 532.0 | 4 | 34107.6 | 34082.1 | 0.9993 | -0.07 |
| 550.0 | 5 | 33925.1 | 33885.0 | 0.9988 | -0.12 |

## Fit by kill-window band

`calibrate` sets no `kill_time_s`, so the simulator does not model the kill window at all: the sim DPS in this table varies only through the duration matching above. The table groups the parses; its err % column cannot discriminate between bands.

| death after final anchor | parses | mean actual aDPS | sim DPS (fitted) | err % |
|---|---:|---:|---:|---:|
| <20 | 14 | 33927.7 | 34095.1 | 0.49 |
| 20-30 | 13 | 34240.3 | 34126.6 | -0.33 |
| 31-60 | 10 | 34161.9 | 34044.6 | -0.34 |
| >60 | 3 | 33782.6 | 33885.0 | 0.30 |

## Per-action counts at 520.0s, as casts per minute

Casts per minute on both sides. The report's absolute counts were taken over 518.2s fights, so differencing them against sim counts at another duration would carry that ratio silently. Heartbreak Shot, Rain of Death and Bloodletter share one charge pool and are only comparable as the combined row: the simulator is single-target, so it converts every charge into Heartbreak Shot.

| action | sim /min | top-10 /min (report) | delta | delta % |
|---|---:|---:|---:|---:|
| ApexArrow | 1.065 | 0.973 | 0.093 | 9.5 |
| ArmysPaeon | 0.458 | - | - | - |
| Barrage | 0.577 | 0.579 | -0.002 | -0.3 |
| BattleVoice | 0.577 | 0.579 | -0.002 | -0.3 |
| BlastArrow | 1.061 | 0.949 | 0.111 | 11.7 |
| BurstShot | 14.370 | - | - | - |
| CausticBite | 0.157 | - | - | - |
| EmpyrealArrow | 3.923 | 3.937 | -0.014 | -0.3 |
| HeartbreakShot | 7.427 | 6.553 | 0.873 | 13.3 |
| IronJaws | 1.343 | 1.308 | 0.035 | 2.7 |
| MagesBallad | 0.458 | - | - | - |
| PitchPerfect | 2.655 | 2.814 | -0.158 | -5.6 |
| RadiantEncore | 0.577 | 0.579 | -0.002 | -0.3 |
| RadiantFinale | 0.577 | 0.579 | -0.002 | -0.3 |
| RagingStrikes | 0.577 | 0.579 | -0.002 | -0.3 |
| RainOfDeath | 0.000 | 0.831 | -0.831 | -100.0 |
| RefulgentArrow | 5.932 | - | - | - |
| ResonantArrow | 0.577 | - | - | - |
| Sidewinder | 0.577 | - | - | - |
| Stormbite | 0.157 | - | - | - |
| WanderersMinuet | 0.577 | - | - | - |
| ChargeSpenders (combined) | 7.427 | 7.384 | 0.043 | 0.6 |
| All casts | 43.623 | 45.270 | -1.647 | -3.6 |

GCDs per minute: sim 25.239, report 25.311.

## Per-parse residuals

| rank | duration_s | actual aDPS | sim DPS | err % |
|---:|---:|---:|---:|---:|
| 1 | 509.9 | 35132.0 | 34129.9 | -2.85 |
| 2 | 512.7 | 34915.7 | 34129.9 | -2.25 |
| 3 | 532.1 | 34858.9 | 34082.1 | -2.23 |
| 4 | 507.4 | 34748.5 | 34129.9 | -1.78 |
| 5 | 502.6 | 34644.6 | 34069.0 | -1.66 |
| 6 | 507.7 | 34432.7 | 34129.9 | -0.88 |
| 7 | 550.6 | 34426.5 | 33885.0 | -1.57 |
| 8 | 520.4 | 34416.8 | 34087.0 | -0.96 |
| 9 | 525.9 | 34394.7 | 34087.0 | -0.89 |
| 10 | 514.4 | 34363.5 | 34129.9 | -0.68 |
| 11 | 522.0 | 34359.1 | 34087.0 | -0.79 |
| 12 | 506.4 | 34348.7 | 34129.9 | -0.64 |
| 13 | 527.5 | 34294.2 | 34082.1 | -0.62 |
| 14 | 510.9 | 34263.9 | 34129.9 | -0.39 |
| 15 | 501.0 | 34243.1 | 34069.0 | -0.51 |
| 16 | 510.9 | 34220.4 | 34129.9 | -0.26 |
| 17 | 508.7 | 34156.3 | 34129.9 | -0.08 |
| 18 | 501.6 | 34123.1 | 34069.0 | -0.16 |
| 19 | 510.0 | 34036.3 | 34129.9 | 0.27 |
| 20 | 506.2 | 34020.9 | 34129.9 | 0.32 |
| 21 | 557.6 | 33944.9 | 33885.0 | -0.18 |
| 22 | 506.2 | 33912.7 | 34129.9 | 0.64 |
| 23 | 506.1 | 33896.5 | 34129.9 | 0.69 |
| 24 | 511.8 | 33868.2 | 34129.9 | 0.77 |
| 25 | 543.7 | 33851.4 | 33885.0 | 0.10 |
| 26 | 505.1 | 33765.1 | 34069.0 | 0.90 |
| 27 | 568.6 | 33755.4 | 33885.0 | 0.38 |
| 28 | 508.8 | 33744.4 | 34129.9 | 1.14 |
| 29 | 521.6 | 33739.9 | 34087.0 | 1.03 |
| 30 | 517.0 | 33707.7 | 34087.0 | 1.13 |
| 31 | 496.1 | 33706.4 | 34069.0 | 1.08 |
| 32 | 503.3 | 33670.7 | 34069.0 | 1.18 |
| 33 | 511.2 | 33660.1 | 34129.9 | 1.40 |
| 34 | 503.5 | 33659.4 | 34069.0 | 1.22 |
| 35 | 559.5 | 33647.5 | 33885.0 | 0.71 |
| 36 | 528.9 | 33641.5 | 34082.1 | 1.31 |
| 37 | 509.0 | 33640.3 | 34129.9 | 1.46 |
| 38 | 527.5 | 33635.9 | 34082.1 | 1.33 |
| 39 | 509.7 | 33618.0 | 34129.9 | 1.52 |
| 40 | 503.5 | 33612.0 | 34069.0 | 1.36 |

## Unverified assumptions

- Army's Muse / Army's Ethos haste table (1 / 2 / 4 / 12 % by stacks, 30 s Ethos carry-over): not in the brief or the repository - simulator assumption.
- Apex Arrow 140 potency at 20 gauge to 700 at 100: both endpoints are the official job guide's Patch 7.5 values, but the shape of the curve between them is not published - the linear interpolation is the simulator's assumption.
- Non-DoT status ids (Hawk's Eye, the buffs, the ready markers, the song statuses) are internal to the simulator; the engine only compares action.statusgainedid to buff.id, so they are self-consistent but unverified against the live client.
- Radiant Encore potency 700 / 800 / 1100 by coda count: taken from the official job guide; Icy Veins' 7.0 changelog listed 500 / 600 / 900 - flagged, not resolved.
- Barrage's Hawk's Eye is guaranteed while every other source rolls job.hawks_eye_proc_chance (35 %): Burst Shot, Stormbite, Caustic Bite, Iron Jaws and Ladonsbite all move together with that one knob, and Barrage's grant is written as certain in actions.json so the knob does not gate it (MECHANICS_CORRECTIONS.md item 7) - the scope of the knob is the assumption.
- Barrage (a 10 s window) does one of two things, per weaponskill, and never both: Refulgent Arrow lands three times (statuses.json weaponskill_hits = 3, so 280 -> 840) and it is the only action the job guide gives the triple hit to, while the AoE Hawk's Eye weaponskills take a flat potency increase instead (actions.json barrage_potency: Shadowbite 200 -> 300 per target; Wide Volley's 140 -> 220 is the same rule below level 72 but has no simulator record, since Wide Volley is absent from CielBardData.Actions). Heavy Shot, Burst Shot, Ladonsbite, Quick Nock, Resonant Arrow, Apex, the DoTs, Radiant Encore and every off-GCD neither benefit from the buff nor consume it. The potencies come from the tooltips; what stays the simulator's model is that an ineligible weaponskill leaves the buff untouched instead of wasting it (MECHANICS_CORRECTIONS.md item 8).
- The Barrage and Radiant Finale transform windows are 30 s (ResonantArrowReady, RadiantEncoreReady) and Battle Voice, Radiant Finale and Raging Strikes last 20 s (MECHANICS_CORRECTIONS.md items 8, 9 and 12) - taken from the guides, not measured on the live client.
- Apex Arrow, Blast Arrow, Resonant Arrow and Radiant Encore are modelled as AoE: Apex Arrow at full potency to every target, the other three at full potency to the first and 50 % to each of the rest. The simulator has no geometry, so a straight line (Apex, Blast Arrow), a cone (Ladonsbite) and a circle around the target (Shadowbite, Rain of Death, Radiant Encore) all hit the same clustered pack - the best case for all of them. Multi-target DPS is an upper bound, not an encounter result.
- Bloodletter 130 potency: kept in the tables but the action is disabled at level 100, where it is trait-upgraded to Heartbreak Shot (180) - brief/game discrepancy.
- oGCD animation lock of 0.6 s: the brief says 0.6, while measured MMOMinion gaps in HANDOFF.md were 640-719 ms including client overhead - flagged, configurable.
- Linear dummy HP model (hp% = 100 * (1 - t / seconds)) used to drive the engine's TTK estimator and therefore its terminal and ideal-finish bands - modelling choice.
- Repertoire procs are modelled on the song timer alone (80 % every 3 s from 42 s remaining down to 3 s, none in the final 3 s) and independent of DoT presence (sim/MECHANICS_CORRECTIONS.md item 1) - assumption, not verified in the client. The DoT independence is the job-table flag repertoire_independent_of_dots, which defaults to true; set it to false to make a proc require a DoT on the target.
- Base crit / DH are the merged report's top-10 event rates (25.366 % / 28.587 %) with the simulator's own buff uptimes deconvolved out, because those observed rates already contain Wanderer's Minuet, Army's Paeon and Battle Voice. They are still event rates rather than damage-weighted rates, and the parses' external raid buffs are not separable - flagged. Check the realized rates the fight and batch reports print against 25.366 % / 28.587 %.

## Known limitations

- aDPS includes external raid buffs; the single scalar absorbs them, so `potency_to_damage` is not a pure stat conversion factor.
- The 40 parses come from one encounter (Vamp Fatale) with real movement, targeting and downtime; the simulator fights a stationary dummy, so the scalar also absorbs the average uptime difference.
- Raw combat events are not on disk, so per-action counts can only be compared against the merged report's top-10 means, not against a per-parse distribution.
- The fit is a single multiplicative scalar. It cannot correct a rotation-shape error: check the per-action count table before trusting the DPS number.
- Kill-window bands are derived from `death_after_final_anchor_s`, which is a proxy for how much of the final burst landed before the boss died.
- The kill-window band table cannot discriminate between bands: `calibrate` sets no `kill_time_s`, so the simulator does not model the kill window at all and the sim DPS in that table varies only through the duration matching. Read it as a grouping of the parses, not as a test of the model.
- A one-parameter multiplicative fit constrains the DPS *level* only. It carries no information about rotation shape, and because the scalar is fitted as sum(aDPS) / sum(sim DPS) the mean residual is zero by construction. The honest check is the R^2 against the constant-mean null printed in the header, plus the per-action rate table.
- The fit is against single-target parses only. `enemies > 1` puts identical dummies on one ring inside every AoE radius, so nothing in the calibration constrains the multi-target numbers.
- Bard auto attacks are ~7-10 % of real aDPS. `stats.auto_attack_dps` ships at 0.0, so they are not modelled and the single scalar absorbs them; that makes them scale with potency output rather than with time, which biases any experiment that moves GCD count or uptime without moving potency (the ping sweep, downtime windows, GCD_ONLY). Set `auto_attack_dps` to model them explicitly.

# Analysis (hand-written)

Everything above this line is generated by `python -m sim.calibrate` and is overwritten on
every run; the same content is in `sim/output/calibration.json`. Everything below is the
analysis the generated report cannot produce on its own, and it must be re-appended after a
regeneration.

**The generated head above is the 2026-09-18 re-run: engine 0.5.2, corrected Patch 7.5
potencies, `potency_to_damage = 128.5594`, seeds 1-150 per duration anchor.** Everything
below this preamble is the **2026-09-17 analysis against engine 0.5.0 on the old potency
curve** (`potency_to_damage = 132.401588`, Apex 100-600, Blast 600, Resonant 600). It is
kept because its reasoning, attributions and diagnostic method are what produced the 0.5.1
engine changes and none of that reasoning has been invalidated - but **its DPS numbers,
scalars and p-values were measured on data that has since been corrected.** Read it for the
*why*; read `sim/output/FINDINGS.md` section 4 for the *what*.

Specifically, on the current tree:

- **Section A's scalar is superseded.** 132.4016 -> **128.5594**; the corrected potencies
  added +3.0 %. Residual 0.98 % mean / 2.85 % max. The engine now sits **1.37 %** below the
  top-10 mean aDPS of 34,633.4 at its shipped defaults.
- **Section C's count gaps are superseded and mostly closed.** Empyreal Arrow -12.1 % ->
  **-0.3 %**, Iron Jaws -5.8 % -> **+2.7 %**, charge spenders -1.3 % -> **+0.6 %**. Apex
  Arrow moved the other way, -1.4 % -> **+9.5 %**, because `apexOffcycleGauge` is now 80.
  See FINDINGS 4.1.
- **Section E is superseded and its conclusion survives with a different mechanism.**
  `chargePoolSeconds = 25` is still right, but 35 no longer collapses: re-swept at 300
  paired seeds on 0.5.2 it loses 0.98 Heartbreak casts and -27 DPS (p = 0.37) where it lost
  5.6 casts and -281 DPS on 0.5.0. That is the `nextBurstSeconds()` skew fix showing up
  exactly where section E predicted it would. `sweep_chargepool.csv` now holds the 0.5.2
  data. See FINDINGS 4.3.
- **Section F's ranked list is superseded by FINDINGS 3.4 and 4.5.** Items 1, 2 and 3
  shipped in 0.5.1; the Apex verdict was re-confirmed on the corrected curve (80 beats 90
  by +0.237 %, p = 0.000079); the only open recommendation is
  `apexHoldForBurstSeconds` 35 -> 0 at p = 0.0524.
- **Sections B and D have not been re-measured** on the corrected curve.

Each claim below names the command that produced it, and the raw CSVs sit next to this file
in `sim/output/`. All of them used `pulse 30 ms`, `ping 0 ms`, one enemy, no downtime, no
potion and `--stat potency_to_damage=132.401588`. Sample sizes are stated per experiment and
are never below 100 seeds.

The reports beside this file are the authority where a section summarises one:
`sim/output/sweep_apex.md` (re-run for 0.5.2), `sim/output/empyreal_report.md` and
`sim/output/pp_ironjaws_report.md` (still 0.5.0). The decision-oriented digest of all four
documents is `sim/output/FINDINGS.md`.

## A. What the corrections changed, and who the engine is

The mechanics-corrections pass (Barrage's triple hit, `statuses.json`
`weaponskill_hits = 3` spent on the next `multi_hit_eligible` weaponskill) moved damage
without moving the rotation.

| quantity | before corrections | after corrections |
|---|---:|---:|
| fitted `potency_to_damage` | 136.7979 | **132.4016** |
| implied simulated potency output | - | **+3.3 %** |
| residual mean abs / max over 40 parses | 0.99 % / 2.78 % | 0.99 % / 2.73 % |
| model R^2 against the constant-mean null | 0.0326 | 0.0294 |
| Iron Jaws /min at 520 s | 1.222 | 1.232 |
| Pitch Perfect /min at 520 s | 2.676 | 2.678 |
| Apex Arrow /min at 520 s | 0.958 | 0.959 |
| all casts /min at 520 s | 43.069 | 43.071 |

The scalar is fitted as `sum(aDPS) / sum(sim DPS)`, so it moves inversely with potency
output: 136.7979 / 132.4016 = 1.0332 is the +3.3 % (the single 510 s measurement quoted in
`sim/README.md` was +2.9 %; the fit averages over the five calibration durations). Every
per-action rate moved by less than 1 %. **The corrections changed what a cast is worth, not
what the engine casts** - which is the result you want from a damage-table correction, and
it means every rotation finding measured before the pass still stands in relative terms.

A second correction in the same pass is not visible in any number here and matters anyway:
`Simulation._apply_job_overrides` now validates `FightConfig.job_overrides` against
`job.json` and re-runs `sim.tables._validate_job` on the merged table. Before it, a
misspelled override was accepted silently, left the default in place, and reported a clean
run that had tested nothing. Two of the three investigations below drive the simulator
through overrides.

Where that leaves the engine:

| quantity | value |
|---|---:|
| fitted `potency_to_damage` | **132.4016** (from 100.0, x1.324016) |
| sim DPS at 510 s, no kill window, 150 seeds | **34,171.4** +/- 45.0 (sd 550.8) |
| all-40 parse mean aDPS | 34,076.9 |
| **top-10 parse mean aDPS** | **34,633.4** |
| sim vs top-10 mean | **-1.33 %** |

The scalar is fitted against all 40 parses, so matching their mean is arithmetic, not
evidence. The number that carries information is the last row: **the shipped engine
simulates as a middle-of-the-top-40 Bard, about 1.3 % below the top-10 mean**, and section
C shows that roughly 0.75 of those 1.33 points is one specific, fixable rule.

```
python -m sim.batch --seconds 510 --seeds 1-150 --workers 11 --stat potency_to_damage=132.401588
```

## B. Kill-time bands, with the kill window actually modelled

The generated "Fit by kill-window band" table above cannot discriminate between bands
because `sim.calibrate` never sets `kill_time_s`. This section runs the experiment it is
missing, at **120 seeds per band**.

In the simulator the burst anchors land at about 6, 128, 250, 371 and **482 s**, so a
parse's `death_after_final_anchor_s = d` maps onto a simulated fight length of `482 + d`.

```
python -m sim.sweep --kill-time 510 --seeds 1-120 --workers 11 \
  --stat potency_to_damage=132.401588 --axis "seconds=494,507,527,552" \
  --csv sim/output/killband.csv
python -m sim.sweep --seeds 1-120 --workers 11 \
  --stat potency_to_damage=132.401588 --axis "seconds=494,507,527,552" \
  --csv sim/output/killband_nokill.csv
```

| band | real parses | real mean aDPS | sim fight | sim DPS, kill window on | err % | same length, no kill window | cost of the kill window |
|---|---:|---:|---:|---:|---:|---:|---:|
| <20 s | 14 | 33,927.7 | 494 s (d=12) | 33,493.7 +/- 53.0 | **-1.28** | 33,450.5 +/- 55.0 | **+43.2** |
| 20-30 s | 13 | 34,240.3 | 507 s (d=25) | 33,830.2 +/- 50.6 | **-1.20** | 34,054.3 +/- 52.4 | -224.1 |
| 31-60 s | 10 | 34,161.9 | 527 s (d=45) | 33,989.4 +/- 49.8 | **-0.51** | 34,066.7 +/- 51.2 | -77.3 |
| >60 s | 3 | 33,782.6 | 552 s (d=70) | 33,766.9 +/- 47.6 | **-0.05** | 33,818.2 +/- 46.2 | -51.3 |

Read across, not down: the level offset is not a fit error, it is the cost of the kill
window itself, and it is only positive in the `<20 s` band where terminal dumping has
something to dump.

**Shape agreement.** Both sides say a fight that ends immediately after the final burst is
a bad place to end and that the middle bands are better. Real spread across the four bands
is 457.7 DPS (1.35 %); the simulator's is 495.7 DPS (1.48 %).

**Shape disagreement, and it is the same one as last pass.** The real peak is `20-30 s`;
the simulator's peak is `31-60 s`. The engine under-rewards the band the merged report
singles out as the preferred one by about 0.7 points relative to its own best band. The
suspects are unchanged - `terminalTTK = 20` opens the terminal branch late and
`dotMinimumTTK = 18` stops DoT refreshes only in the last 18 s, so a fight that dies 25 s
after the final anchor spends its whole tail in the ordinary sustained branch, pooling
charges for a sixth burst that never happens. See sweep candidate 3, and note the
`terminalDumping` result in section F that arrived from the Pitch Perfect investigation.

## C. Where the sim disagrees with the top-10 counts, and why

Rates are per minute, from the generated per-action table at 520 s, seeds 1-150.

| # | action | sim /min | report /min | delta % | verdict |
|---:|---|---:|---:|---:|---|
| 1 | EmpyrealArrow | 3.462 | 3.937 | **-12.1** | real engine defect, diagnosed |
| 2 | IronJaws | 1.232 | 1.308 | -5.8 | real defect, no measurable DPS cost |
| 3 | PitchPerfect | 2.678 | 2.814 | -4.8 | **not a defect - an artefact of the missing kill window** |
| 4 | RainOfDeath | 0.000 | 0.831 | -100.0 | modelling scope, not a defect |
| 5 | HeartbreakShot | 7.292 | 6.553 | +11.3 | the other half of #4 |
| 6 | ChargeSpenders (combined) | 7.292 | 7.384 | -1.3 | agreement |
| 7 | All casts | 43.071 | 45.270 | -4.9 | see below |
| 8 | ApexArrow / BlastArrow | 0.959 / 0.956 | 0.973 / 0.949 | -1.4 / +0.7 | agreement |
| 9 | GCDs per minute | 25.255 | 25.311 | -0.2 | agreement |
| 10 | Raging/BV/RF/Encore/Barrage | 0.577 each | 0.579 each | -0.3 | agreement |

### 1. Empyreal Arrow, -12.1 %: one use lost per two-minute window

Deterministic - **every seed casts Empyreal Arrow exactly 30.00 times in 510 s**, against
34 at its 15 s recast and the report's 34.0. `sim/output/empyreal_report.md` instruments
every pulse of the fight and attributes the 61.91 s of ready-but-uncast recast time:

| gate | s/fight | share |
|---|---:|---:|
| `holdEmpyreal` (`CielBard_Rotation.lua:958`) | **42.57** | **68.8 %** |
| animation lock inside the burst | 14.39 | 23.2 % |
| clip guard `weaveMinGcdRemaining` inside the burst | 3.39 | 5.5 % |
| animation lock in the opener | 0.63 | 1.0 % |
| GCD window / `maxWeaves` / another oGCD took the slot | 0.90 | 1.5 % |
| `requestThrottleMs` / engine pulse cadence | **0.00** | **0.0 %** |

It is not weave congestion. The `ctx.nextBurst <= 5` hold on line 958 is really a **~15 s**
hold, because `nextBurstSeconds()` (`:236-252`) returns 0 as soon as the *first* enabled
burst action is ready, and Radiant Finale's 110 s recast comes up ~7.5 s before Raging
Strikes' 120 s. Fifteen seconds is exactly one Empyreal recast. Disabling only Radiant
Finale with the hold rule fully in place collapses the hold from 42.16 s to 1.33 s and
raises Empyreal from 30.00 to 33.67 - the isolation proof.

Confirmed on the only switch that reaches that line, **150 seeds**:

```
python -m sim.sweep --seconds 510 --kill-time 510 --seeds 1-150 --workers 11 \
  --stat potency_to_damage=132.401588 --axis "resourcePooling=true,false" \
  --csv sim/output/diag_pooling150.csv
```

| resourcePooling | n | DPS mean | DPS sem | Empyreal | Apex | Blast | Heartbreak |
|---|---:|---:|---:|---:|---:|---:|---:|
| false | 150 | **34,047.3** | 52.2 | **33.63** | 10.17 | 8.41 | 63.85 |
| true (shipped) | 150 | 33,793.6 | 43.5 | 30.00 | 9.71 | 8.05 | 63.12 |

**+253.7 DPS, +0.75 %, 3.7 sigma**, and Empyreal lands on 33.63 against the report's 34.0.
The paired 60-seed isolation in `empyreal_report.md` puts the same effect at +225.8 DPS,
+0.67 %, t = +3.53, and shows that **all** of it is the Empyreal hold: keeping
`resourcePooling` on while zeroing `chargePoolSeconds` and `apexHoldForBurstSeconds` is
worth -15.4 DPS (t = -0.28).

Four lost Empyreal Arrows are 1,040 potency out of ~99,800, 1.04 % of raw potency, against
a measured 0.67-0.75 % of DPS. The gap to the top-10 mean is 1.33 %. **One rule accounts
for more than half of it.** The fix is an engine change and is written out in
`empyreal_report.md` section 7; it is ranked first in section F below.

### 2. Iron Jaws, -5.8 %: a real defect that costs nothing measurable

`sim/output/pp_ironjaws_report.md` counts **1.450 DoT fall-off events per fight** (Caustic
Bite uptime 98.65 %), each costing two hard casts instead of one Iron Jaws. The cause is
priority, not the threshold: Blast Arrow (`:737`), Resonant Arrow (`:739`), Radiant Encore
(`:741`) and Apex Arrow (`:745`) all precede the refresh at `:766`, and
`dotRefreshSeconds = 3.0` is only 1.2 GCDs wide at the simulated 2.37 s GCD. Blocking casts
per fight: Blast 0.625, Resonant 0.550, Apex 0.400, Encore 0.375.

Fall-off events against the threshold, 40 seeds: 3 s -> 1.450, 4 s -> 1.350, 5 s -> 1.250,
**6 s -> 0.300**, 7 s -> 0.150. The cliff is at 6 s, exactly where the window outlasts two
GCDs - which confirms the diagnosis and is the wrong fix, because it discards 30-47 s of
DoT duration per fight. That is why the whole `dotRefreshSeconds` x `snapshotIronJaws` grid
is flat: 150 seeds, kill window on (`sim/output/sweep_dots.csv`) spans 112 DPS (0.33 %) at
sem ~45, and the same grid with the kill window off (`sim/output/sweep_dots_nokill.csv`)
spans 98 DPS and **ranks the points in a different order** - the definition of noise.

The recommended fix is a narrow urgency pre-empt ahead of the proc-consumers, written out
in `pp_ironjaws_report.md` section 5. Expected value ~+158 potency, +0.16 %, below what 150
seeds resolve; verify it by counts, not by DPS.

### 3. Pitch Perfect, -4.8 %: an artefact of how `sim.calibrate` runs, not a defect

This entry has flipped since the previous pass. Full stack accounting over 40 seeds, 510 s,
no kill window: income 64.375 Repertoire procs inside Wanderer's Minuet (50.375 from the
song timer, 14.000 from Empyreal), 62.825 spent, **0.475 lost to the 3-stack cap**,
**0.000 lost at song end**, 1.075 unspent at the fight clock. The budget sums exactly. The
`songRemaining <= 3` dump fires 3.65 times per fight against the four Wanderer's Minuet
songs that complete in 510 s, and Wanderer's Minuet holds 36.1 % of the sim's song cycle
against the top-10's 36.2 %, so there is no uptime to win back either.

**With `--kill-time 510` the engine casts 26.025 Pitch Perfect = 3.062/min, 8.8 % *above*
the top-10 2.814** - same 62.6 stacks, split into more casts because the terminal band
dumps at one stack (1.40 -> 6.88 one-stack casts). The -4.8 % in the table above is
`sim.calibrate` not setting `kill_time_s`, which the generated report already warns about
for the DPS columns and which turns out to bite the count table too. **No engine change is
warranted for Pitch Perfect**; `ctx.repertoire >= 3` and `ctx.songRemaining <= 3` are
hard-coded and measure correct.

### 4, 5. Rain of Death / Heartbreak Shot: scope, not behaviour

The simulator is single target, so every shared charge becomes a Heartbreak Shot.
Differencing against the report's Heartbreak-only rate reports +11.3 % overuse where the
combined charge pool is in fact 1.3 % *under*-used. Not a defect, and not testable until
the simulator grows a multi-target damage model.

### 7. All casts, -4.9 %: 70 % accounted for, 30 % out of scope

The sim is 2.199 casts/min short. Accounted for: Rain of Death 0.831, Empyreal 0.475, Pitch
Perfect 0.136, Iron Jaws 0.076, Apex 0.013, the five two-minute cooldowns 0.010 - 1.541
total. The residual **0.658/min (about 5.7 casts per fight)** is unmodelled: Ladonsbite and
Shadowbite, and the utility casts a real pull contains (Warden's Paean, Troubadour,
Nature's Minne, Repelling Shot, Peloton).

## D. Two calibration caveats the scalar is hiding

1. **The potion.** All 40 parses used one; `sim.calibrate` runs without one. At 510 s over
   **150 seeds**: 34,541.3 +/- 46.1 with `--potion` against 34,171.4 +/- 45.0 without,
   **+369.9 DPS, +1.08 %, 5.7 sigma** (two potions land in a 510 s fight). Re-fitting with
   `--potion` would drop `potency_to_damage` by about 1.1 %, to roughly 131.0. The scalar
   currently absorbs the potion.
2. **Auto attacks.** `stats.auto_attack_dps` ships at 0.0 and Bard auto attacks are 7-10 %
   of real aDPS, so the scalar absorbs those too - and absorbs them as a multiple of
   potency rather than as a function of time. Any experiment that moves GCD count or uptime
   without moving potency (ping, downtime, `GCD_ONLY`) is biased by this.

Together these mean `potency_to_damage = 132.40` is a *fitting constant*, not a stat
conversion. Use it to compare simulator configurations against each other, which is what it
is good for; do not read it as a gear or stat statement.

## E. Heartbreak `chargePoolSeconds`: the shipped default is right, 35 s is not

> **Re-swept on 0.5.2.** 7a was fixed in 0.5.1 and this table was re-run at 300 paired
> seeds: 25 still wins, but 35 no longer collapses (-0.98 Heartbreak casts, -27 DPS,
> p = 0.37, against -5.6 casts and -281 DPS here). `sweep_chargepool.csv` now holds the
> 0.5.2 data; `sim/output/FINDINGS.md` 4.3 is the current report.

```
python -m sim.sweep --seconds 510 --kill-time 510 --seeds 1-100 --workers 11 \
  --stat potency_to_damage=132.401588 --axis "chargePoolSeconds=0,15,25,35" \
  --csv sim/output/sweep_chargepool.csv
```

| chargePoolSeconds | n | DPS mean | DPS sem | GCDs | Heartbreak casts | vs 25 s | sigma |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 15 | 100 | 33,824.7 | 55.6 | 214.81 | 63.79 | +15.4 | 0.2 |
| **25 (shipped)** | 100 | **33,809.3** | 56.9 | 214.93 | 63.16 | +0.0 | - |
| 0 | 100 | 33,745.2 | 56.2 | 214.80 | 63.83 | -64.1 | 0.8 |
| 35 | 100 | 33,528.2 | 63.9 | 214.92 | **57.54** | **-281.1** | **3.3** |

**The only statistically real result is that 35 s is bad.** 0 s and 15 s sit inside one
sigma of the shipped 25 s. The mechanism at 35 s is in the counts: Heartbreak collapses by
**5.6 charges**. Pooling starts 35 s before the burst but a charge recharges in 15 s, so
the third charge caps and every later Mage's Ballad proc is thrown away.

`empyreal_report.md` section 7a adds a cause this table could not see: `nextBurstSeconds()`
reports ~7.5 s early, so the *effective* pooling window at the shipped 25 is already ~32 s
and 35 becomes ~42 s. **If 7a is fixed, this table must be re-swept** - the shipped 25 will
behave like a true 25 for the first time.

Note that 0 s does **not** recover the Empyreal loss of section C1: `chargePoolSeconds`
gates charges only, while the Empyreal hold is gated on `resourcePooling` itself.

## F. Ranked engine parameters worth changing or sweeping next

Three of the previous pass's six candidates have now been measured to a conclusion. The
full decision digest is `sim/output/FINDINGS.md`.

**1. The Empyreal Arrow pre-burst hold. MEASURED: +0.67 % to +0.75 %, 3.5-3.7 sigma.**
The single largest known gap to the top-10 mean. It is an engine change, not a config
change: give the hold its own key `empyrealHoldForBurstSeconds` defaulting to 0, and fix
`nextBurstSeconds()` to take the maximum remaining cooldown over the enabled burst actions
instead of returning 0 on the first ready one. Both are written out in
`empyreal_report.md` section 7. The `nextBurstSeconds()` fix also un-skews
`chargePoolSeconds` and `apexHoldForBurstSeconds`, which is why section E must be re-run
after it. Still holds at 60 ms ping: +187.3 DPS, t = +2.81, Empyreal 3.927/min against the
parses' 3.937.

**2. `apexOffcycleGauge` 90 -> 80. MEASURED: +0.25 %, p = 0.0003 over 300 paired seeds.**
`sim/output/sweep_apex.md` settles `MECHANICS_CORRECTIONS.md` item 16. The specified
9-point x 60-seed grid could not resolve it (+0.18 %, p = 0.21); five points re-run at 300
seeds give 80 / 0 over the shipped 90 / 35 at +86.7 DPS, t(299) = +3.67, 95 % CI +0.12 % to
+0.39 %. The gauge carries the whole effect (80 vs 90: +0.20 % at hold 0, +0.23 % at hold
35); **`apexHoldForBurstSeconds` is worth nothing measurable** (hold 0 vs 35: +0.06 % at
gauge 90, p = 0.28). Gauge 100 is the worst point, -0.30 % against 80 / 0, and it silently
disables the hold entirely (`ctx.soulVoice < 95` gates it, so the three gauge-100 rows are
bit-identical). Soul Voice overcap is exactly 0.0 at gauge 80 and 90 in all 900 fights, so
overcap is not the mechanism - gauge 100 simply gets 1.42 fewer Apex+Blast pairs.
**Caveat worth carrying:** the shipped 90 / 35 reproduces the parses' 0.973 Apex/min to
0.005, and firing at 80 produces 1.112/min, 14 % above it. Either the top 10 were not
firing at 80, or the simulator's Repertoire model overstates gauge income by ~12 %. Item
16's conclusion is confirmed on DPS; its reasoning is contradicted.

**3. Terminal-window policy: `terminalTTK` x `idealKillMax` x `terminalDumping`.**
Section B's shape disagreement, still unresolved, and now with a concrete lead. 400 seeds
with the kill window on (`sim/output/sweep_terminaldump400.csv`) put
`terminalDumping=false` at **33,924.5 against 33,820.2, +104.4 DPS, +0.31 %, 2.6 sigma**.
It is not Pitch Perfect fragmentation - the effect is `CielBard_Rotation.lua:748` dropping
the Apex threshold to 20 gauge in the terminal band, which buys 1.57 extra Apex casts near
the 100-potency floor in place of ~237-potency fillers. **Do not act on a single-axis
2-point sweep**: `terminalDumping` also governs charge and Soul Voice dumping. Run the grid.

```
python -m sim.sweep --kill-time 507 --seconds 507 --seeds 1-150 --workers 11 \
  --stat potency_to_damage=132.401588 \
  --axis "terminalTTK=20,30,45" --axis "idealKillMax=30,45" \
  --csv sim/output/sweep_terminal.csv
```

Run it at 507 s (the 20-30 s band) and again at 494 s; a parameter that helps one band and
hurts the other is a branch-threshold problem, not a tuning problem.

**4. Iron Jaws urgency pre-empt (`dotUrgentSeconds`).** An engine change with an expected
+0.16 %, which is below the 0.13 % that 150 seeds resolve. Verify it by counts:
`dotUrgentSeconds = 0` must reproduce today's 10.70 / 2.30 / 2.30 exactly, and 1.5 should
give Iron Jaws ~12.1 with hard casts back to 1 / 1.

**5. `weaveMinGcdRemaining` x `ping_ms`.** Partly answered by `empyreal_report.md`:
`weaveMinGcdRemaining` at 0.5 or 0.8 is worth -6.5 / -4.4 DPS and moves no count at all,
and the Empyreal fix still pays +187.3 DPS at 60 ms ping. What is still unmeasured is the
whole rotation at 120-150 ms, where the arithmetic in `sim/README.md` says clipping starts.

**6. Song allocation: `wmSwapRemaining` x `mbSwapRemaining` x `apSwapRemaining`.** Lowest
expected payoff and now with a measurement behind that judgement: Wanderer's Minuet holds
36.1 % of the sim's song cycle against the top-10's 36.2 %, and the cycle is 43.8 / 42.5 /
34.9 s against the empirical 43.84 / 42.27 / 34.91.

**Not worth sweeping again:** `chargePoolSeconds` (section E - until 7a lands),
`maxWeaves` (bit-identical to the Empyreal fix alone at 60 ms ping; its 0-ping gain is an
artefact), `requestThrottleMs`, `pulseMs`, `dotRefreshSeconds` x `snapshotIronJaws` (two
150-seed grids that disagree on rank order), and `repertoire_skip_final_tick` (changed
nothing: `wmSwapRemaining = 1.2` has already swapped the song before that roll).

## G. Reproducing this report

```
# generated sections
python -m sim.calibrate --seeds 1-150 --workers 11 --out sim/output/calibration.md --write-scalar

# then the analysis experiments, in order
python -m sim.batch --seconds 510 --seeds 1-150 --workers 11 --stat potency_to_damage=132.401588
python -m sim.batch --seconds 510 --seeds 1-150 --workers 11 --stat potency_to_damage=132.401588 --potion
python -m sim.sweep --kill-time 510 --seeds 1-120 --workers 11 --stat potency_to_damage=132.401588 --axis "seconds=494,507,527,552" --csv sim/output/killband.csv
python -m sim.sweep --seeds 1-120 --workers 11 --stat potency_to_damage=132.401588 --axis "seconds=494,507,527,552" --csv sim/output/killband_nokill.csv
python -m sim.sweep --seconds 510 --kill-time 510 --seeds 1-150 --workers 11 --stat potency_to_damage=132.401588 --axis "resourcePooling=true,false" --csv sim/output/diag_pooling150.csv
python -m sim.sweep --seconds 510 --kill-time 510 --seeds 1-100 --workers 11 --stat potency_to_damage=132.401588 --axis "chargePoolSeconds=0,15,25,35" --csv sim/output/sweep_chargepool.csv
```

The three investigations have their own reproduction sections:
`sim/output/sweep_apex.md`, `sim/output/empyreal_report.md`,
`sim/output/pp_ironjaws_report.md`.

Nothing under `CielBard/` was read for anything but line references, and nothing under it
was modified - the sha256 pins in `tests/test_integration.py` still hold
(`CielBard_Rotation.lua` `94980f7b...`, `CielBard_Data.lua` `e66dd25c...`).
`tests/run_sim_tests.py`, `tests/run_mock_tests.py` and `tests/run_gui_tests.py` were green
before and after.
