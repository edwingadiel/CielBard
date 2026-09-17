# CielBard simulator: findings and decisions

- 2026-09-17. sim 1.0.0 driving engine 0.5.0 **unmodified** (`CielBard_Rotation.lua`
  `94980f7b...`, `CielBard_Data.lua` `e66dd25c...`; the sha256 pins in
  `tests/test_integration.py` hold, `git diff` on `CielBard/` is empty).
- All DPS on the fitted scale `potency_to_damage = 132.401588`
  (`sim/output/stats.override.json`). The scalar is an exact linear multiplier, so every
  percentage, sigma and p-value here is identical at any scale.
- Suites green before and after every experiment: `tests/run_sim_tests.py` (204 tests, 2
  documented `expectedFailure`), `tests/run_mock_tests.py`, `tests/run_gui_tests.py`.
- Sources: `sim/output/calibration.md` (re-run this pass, 150 seeds; >= 100 seeds per
  kill-time band), `sim/output/sweep_apex.md`, `sim/output/empyreal_report.md`,
  `sim/output/pp_ironjaws_report.md`.

**The decision in one paragraph.** The simulated engine sits **1.33 % below the top-10
parse mean**. Two engine changes are now measured well enough to make: give the Empyreal
Arrow pre-burst hold its own key with a default of 0 and fix `nextBurstSeconds()`
(**+0.67 % to +0.75 %**, 3.5-3.7 sigma), and drop `apexOffcycleGauge` from 90 to 80
(**+0.25 %**, p = 0.0003). Together they are most of the gap. A third, an Iron Jaws
urgency pre-empt, is a correctness fix worth about +0.16 % that the simulator cannot
resolve statistically - take it on the counts. Pitch Perfect needs no change at all: the
count gap that opened this investigation is an artefact of how `sim.calibrate` runs.

---

## 1. What the corrections changed

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

The scalar is fitted as `sum(aDPS) / sum(sim DPS)`, so it moves inversely with potency:
136.7979 / 132.4016 = 1.0332. The fitted DPS *level* is pinned to the parses by
construction either way - what the correction bought is that the level is now reached with
the right amount of potency instead of a 3.3 % larger scalar.

**In rates: nothing moved.** Every per-action rate at 520 s changed by under 1 %.

| action /min at 520 s | before | after | top-10 |
|---|---:|---:|---:|
| Iron Jaws | 1.222 | 1.232 | 1.308 |
| Pitch Perfect | 2.676 | 2.678 | 2.814 |
| Apex Arrow | 0.958 | 0.959 | 0.973 |
| Empyreal Arrow | 3.462 | 3.462 | 3.937 |
| all casts | 43.069 | 43.071 | 45.270 |

**This is the result you want from a damage-table correction: it changed what a cast is
worth, not what the engine casts.** Every rotation finding measured before the pass still
stands in relative terms, which is why the three investigations below could re-use
pre-correction diagnoses without re-deriving them.

The second correction produces no number and matters anyway.
`Simulation._apply_job_overrides` now validates `FightConfig.job_overrides` against
`job.json` and re-runs `sim.tables._validate_job` on the merged table; a `None` deletes a
key and the superseded `repertoire_requires_dot` spelling is still accepted. Before it, a
misspelled override was accepted silently, left the default in place, and reported a clean
run that had tested nothing - and two of the three investigations below steer the
simulator entirely through overrides.

**Kill-time bands, re-run at 120 seeds per band** (`sim/output/killband.csv`,
`killband_nokill.csv`):

| band | parses | real mean aDPS | sim fight | sim DPS, kill window on | err % | kill window off | cost of the window |
|---|---:|---:|---:|---:|---:|---:|---:|
| <20 s | 14 | 33,927.7 | 494 s | 33,493.7 +/- 53.0 | -1.28 | 33,450.5 | **+43.2** |
| 20-30 s | 13 | 34,240.3 | 507 s | 33,830.2 +/- 50.6 | -1.20 | 34,054.3 | -224.1 |
| 31-60 s | 10 | 34,161.9 | 527 s | 33,989.4 +/- 49.8 | -0.51 | 34,066.7 | -77.3 |
| >60 s | 3 | 33,782.6 | 552 s | 33,766.9 +/- 47.6 | -0.05 | 33,818.2 | -51.3 |

Real spread across bands 457.7 DPS (1.35 %), simulated 495.7 (1.48 %) - the same
magnitude. The shape still disagrees in one place: the real peak is `20-30 s` and the
simulator's is `31-60 s`. That disagreement is unresolved and is item 4 of section 3.

---

## 2. The Apex sweep verdict

**`MECHANICS_CORRECTIONS.md` item 16 is confirmed on DPS and contradicted on reasoning.**
Full report: `sim/output/sweep_apex.md`.

The grid as specified - `apexOffcycleGauge` {80, 90, 100} x `apexHoldForBurstSeconds`
{0, 15, 35}, 510 s, ping 0, no kill time, 60 seeds per point, 540 fights, 0 rejections -
**cannot resolve the effect**: the hypothesis (80 / 0) beats the shipped default (90 / 35)
by +62.3 DPS, +0.18 %, p = 0.21, 95 % CI -0.11 % to +0.47 %. Resolving 0.18 % at 80 % power
needs ~297 seeds per point.

Five points re-run at **300 paired seeds** settle it:

| gauge / hold | n | DPS mean | sem | Apex | Blast | SV overcap | vs default | % | t | p |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **80 / 0 (hypothesis)** | 300 | **34,247.4** | 35.3 | 9.40 | 9.33 | 0.00 | **+86.7** | **+0.254** | **+3.67** | **0.0003** |
| 80 / 35 | 300 | 34,237.7 | 34.4 | 8.79 | 8.73 | 0.00 | +77.0 | +0.225 | +2.96 | 0.0033 |
| 90 / 0 | 300 | 34,179.8 | 34.0 | 8.45 | 8.39 | 0.00 | +19.1 | +0.056 | +1.08 | 0.2792 |
| **90 / 35 (shipped)** | 300 | 34,160.7 | 32.8 | 8.24 | 8.19 | 0.00 | +0.0 | - | - | - |
| 100 / 0 | 300 | 34,145.0 | 34.5 | 7.98 | 7.97 | 2.35 | -15.7 | -0.046 | -0.59 | 0.5538 |

95 % CI on the headline: **+0.12 % to +0.39 %**. Comparisons are paired on the seed;
unpaired the same difference reads 1.8 sigma and would be called noise.

**Decomposition over the {80, 90} x {0, 35} factorial, 300 seeds:**

- gauge **80 vs 90**: +0.198 % at hold 0 (p = 0.008), +0.225 % at hold 35 (p = 0.003).
  **The gauge carries the whole effect.**
- hold **0 vs 35**: +0.056 % at gauge 90 (p = 0.28), +0.028 % at gauge 80 (p = 0.67).
  **The hold is worth nothing measurable.**
- gauge **100 vs 80 / 0**: -0.299 % (p = 0.0003). 100 is the worst of the three.

**Why the surface is so flat.** GCD count is identical at every point (214.88), so an extra
Apex+Blast pair displaces two ~245-potency fillers rather than adding casts, and the Apex
curve (475 potency at 80 gauge, 537 at 90, 600 at 100) almost exactly compensates the cast
count. Measured potency gain of 80 / 0 over the default is +109.6 (+0.110 %, p < 0.0001) -
about half the DPS gain; the rest is the extra pairs landing inside Raging Strikes and
Battle Voice.

**Soul Voice overcap is not the mechanism.** The counter already existed
(`sim/core.py` -> `FightResult.wasted["soul_voice_overcap"]`, printed by `sim.run` as
`waste soulvoice`); it is **exactly 0 in all 900 fights at gauge 80 and 90**, and 2.35 per
fight at gauge 100 - 0.3 % of the ~800 gauge a fight spends. What gauge 100 costs is 1.42
fewer Apex+Blast pairs.

**Two findings beyond the question asked:**

1. **Item 16's rationale is contradicted while its conclusion is confirmed.** The parses'
   0.973 Apex/min is what the *shipped* 90 / 35 produces (0.978/min, agreement to 0.005).
   Firing at 80 produces **1.112/min, 14 % above the top-10 rate**. So either the top 10
   were not firing at 80, or the simulator's Repertoire/gauge-income model overstates
   income by ~12 %. This is the sharpest test yet of the still-assumed item 1 proc model
   (section 4). The DPS recommendation stands on the DPS measurement alone.
2. **`apexHoldForBurstSeconds` is unreachable at gauge 100.** `CielBard_Rotation.lua` gates
   the hold on `ctx.soulVoice < 95`, so the three gauge-100 rows are bit-identical. Any
   future sweep crossing gauge > 95 with the hold wastes two thirds of its points.

**Verdict: change `apexOffcycleGauge` 90 -> 80. Leave `apexHoldForBurstSeconds` alone**
(drop it for simplicity if wanted, never for DPS - and note it shares `resourcePooling`
with the Empyreal hold, so it needs its own key either way).

Artifacts: `sim/output/sweep_apex.md`, `sweep_apex.csv` (the documented `sim.sweep`
command; rows match to the decimal), `sweep_apex.json` (9 x 60 per-seed series),
`sweep_apex_confirm.json`, `sweep_apex_confirm2.json` (5 points x 300 seeds).

---

## 3. Diagnoses and the ranked engine changes

### 3.1 Empyreal Arrow, -12.1 %: one predicate, one lost cast per burst window

Full report: `sim/output/empyreal_report.md`.

**It is not weave congestion.** Over 510 s, Empyreal sits ready-but-uncast for **61.91 s =
4.13 lost recasts** (30.00 casts of a possible 34). Attribution, seeds 1-10, shipped
defaults:

| gate | s/fight | share |
|---|---:|---:|
| `holdEmpyreal` (`CielBard_Rotation.lua:958`) | **42.57** | **68.8 %** |
| animation lock, in burst | 14.39 | 23.2 % |
| clip guard `weaveMinGcdRemaining`, in burst | 3.39 | 5.5 % |
| animation lock, opener | 0.63 | 1.0 % |
| GCD window / `maxWeaves` / another oGCD took the slot | 0.90 | 1.5 % |
| `requestThrottleMs` / engine pulse cadence | **0.00** | **0.0 %** |

Five gaps per fight - one per burst window - carry 59.49 s, 96.1 % of the loss, each
14.5-18.5 s long. In seed 1, 1078 of 1505 hold pulses (71.6 %) had `nextBurst == 0.0`
exactly.

**Root cause.** `local holdEmpyreal = c.resourcePooling and ctx.burstConfigured and
ctx.nextBurst <= 5 and not ctx.terminal` (`:958`). The "5 s" hold is really **~15 s**,
because `nextBurstSeconds()` (`:236-252`) returns 0 on the *first* ready burst action and
Radiant Finale's 110 s recast comes up ~7.5 s before Raging Strikes' 120 s; add ~2.3 s of
burst-start gating. Fifteen seconds is exactly one Empyreal recast.

**Isolation proof.** Disable only Radiant Finale, leave the hold rule fully in place: hold
drops 42.16 s -> **1.33 s**, Empyreal 30.00 -> **33.67**.

**Measured value of removing the hold.**

| measurement | DPS delta | Empyreal | statistic |
|---|---:|---:|---|
| `resourcePooling=false`, 150 seeds, unpaired (`diag_pooling150.csv`) | **+253.7 (+0.75 %)** | 30.00 -> 33.63 | 3.7 sigma |
| `resourcePooling=false`, 60 paired seeds | **+225.8 (+0.67 %)** | 30.00 -> 33.63 | t = +3.53 |
| same at 60 ms ping | +187.3 (+0.55 %) | 30.00 -> 33.38 | t = +2.81 |

**All of it is the Empyreal hold**, not the other two things `resourcePooling` governs:
keeping pooling on while zeroing `chargePoolSeconds` and `apexHoldForBurstSeconds` is worth
**-15.4 DPS (t = -0.28)**, and every other config point tested leaves Empyreal at exactly
30.00. At 60 ms ping the fixed engine casts 3.927 Empyreal/min against the parses' 3.937.

### 3.2 Pitch Perfect, -4.8 %: not a defect

Full report: `sim/output/pp_ironjaws_report.md`.

The stack budget balances exactly over 40 seeds: income 64.375 Repertoire procs inside
Wanderer's Minuet (50.375 song-timer + 14.000 Empyreal), 62.825 spent, **0.475 lost to the
3-stack cap** (0.7 % of income, 57 potency), **0.000 lost at song end**, 1.075 unspent at
the fight clock. The `songRemaining <= 3` dump fires 3.65x per fight against the four
Wanderer's Minuet songs that complete in 510 s. Wanderer's Minuet holds 36.1 % of the sim's
song cycle against the top-10's 36.2 %, so there is no uptime to win back.
`repertoire_skip_final_tick=false` changes nothing (22.300 -> 22.300): `wmSwapRemaining=1.2`
has already swapped the song before that roll.

**The gap's sign depends on the kill window.** With `--kill-time 510` the engine casts
26.025 Pitch Perfect = **3.062/min, 8.8 % *above* the top-10 2.814** - same 62.6 stacks,
split into more casts because the terminal band dumps at one stack (1-stack casts
1.40 -> 6.88). The calibration's -4.8 % is `sim.calibrate` not setting `kill_time_s`.

**No Lua change is warranted.** `ctx.repertoire >= 3` (`:932`, `:955`) and
`ctx.songRemaining <= 3` (`:955`) are hard-coded and measure correct; giving them config
keys would only let a user make them worse.

### 3.3 Iron Jaws, -5.8 %: a real defect with no measurable DPS cost

10.700 Iron Jaws per fight (8.275 refresh + 2.425 snapshot), 2.300 hard Stormbite, 2.300
hard Caustic Bite, **1.450 DoT fall-off events per fight**, Caustic Bite uptime 98.65 %.

**Cause is priority, not the threshold.** Blast Arrow (`:737`), Resonant Arrow (`:739`),
Radiant Encore (`:741`) and Apex Arrow (`:745`) all precede the refresh at `:766`, and
`dotRefreshSeconds = 3.0` is 1.2 GCDs at the simulated 2.37 s GCD. Blockers per fight:
Blast 0.625, Resonant 0.550, Apex 0.400, Encore 0.375 - 1.95 blocking GCDs over 1.45
events, i.e. chains up to two consumers deep (4.7-5.0 s). Seed-7 trace: Iron Jaws at
128.96 -> Apex 170.86 (3.10 s left) -> Blast 173.36 (0.60 s left) -> both DoTs expire
173.96 -> Stormbite 175.86 + Caustic 178.36.

Fall-off events vs `dotRefreshSeconds`, 40 seeds: 3 s -> 1.450, 4 s -> 1.350, 5 s -> 1.250,
**6 s -> 0.300**, 7 s -> 0.150. The cliff is at 6 s, exactly where the window outlasts two
GCDs. Raising the threshold is nevertheless **the wrong fix**: it discards 30-47 extra
seconds of DoT duration per fight, which is why its DPS is flat.

**No config knob moves DPS.** `dotRefreshSeconds` x `snapshotIronJaws` at 150 seeds with
the kill window on (`sweep_dots.csv`) spans 112 DPS (0.33 %) at sem ~45, widest separation
1.7 sigma; the same grid with the kill window off (`sweep_dots_nokill.csv`) spans 98 DPS
**and ranks the points in a different order**. Counts agree to within 0.2 casts across both
grids. `snapshotIronJaws=false` converts 2.425 snapshot casts into 1.300 ordinary refreshes
(net Iron Jaws -1.125) and moves DPS by -9 +/- 130.

### 3.4 The recommended engine changes, ranked

Nothing below has been made. The simulator's purpose is to test the shipped Lua unmodified;
every measurement above was taken through `FightConfig.engine_config`, the override path
behind `sim.sweep --axis`.

| # | change | expected DPS | confidence | evidence |
|---:|---|---:|---|---|
| **1** | `nextBurstSeconds()` -> max over enabled burst actions, **and** a new `empyrealHoldForBurstSeconds` defaulting to **0** | **+0.67 % to +0.75 %** | **High** | 150-seed sweep at 3.7 sigma; 60 paired seeds t = +3.53; isolation proof; holds at 60 ms ping (t = +2.81) |
| **2** | `apexOffcycleGauge` 90 -> 80 | **+0.25 %** | **High (within model)** | 300 paired seeds, t(299) = +3.67, p = 0.0003, CI +0.12 % to +0.39 %; consistent in sign at every sample size |
| **3** | Iron Jaws urgency pre-empt: `dotUrgentSeconds = 1.5` ahead of the proc-consumers | +0.16 % (estimated) | **Medium on DPS, High on correctness** | Arithmetic from measured counts; below the 0.13 % that 150 seeds resolve - verify by counts |
| 4 | Terminal-window policy (`terminalTTK` / `idealKillMax` / `terminalDumping`) | +0.31 % observed, confounded | **Low - investigate first** | 400 seeds, `terminalDumping=false` +104.4 DPS at 2.6 sigma, but the axis governs three behaviours at once |
| 5 | Remove `apexHoldForBurstSeconds` | **0.00 %** | High that it is zero | 300 seeds: 0 vs 35 is p = 0.28 at gauge 90, p = 0.67 at gauge 80 |
| - | Pitch Perfect | no change | High | Stack budget balances; gap is a `sim.calibrate` artefact |

**Do 1 and 2. Do 3 for correctness. Do not act on 4 yet. 5 is optional and cosmetic.**

Items 1 and 2 are not additive by measurement - they have never been run together - but
they are mechanically independent (an oGCD hold and a GCD gauge threshold), and if they
add, they close roughly 0.9 to 1.0 of the 1.33 % gap to the top-10 mean.

**Change 1, as described in `empyreal_report.md` section 7.** Two independent defects meet
on line 958.

*1a.* `nextBurstSeconds()` (`CielBard_Rotation.lua:236-252`) answers "how long until the
burst window opens" and every caller uses it that way, but it returns 0 as soon as the
*first* enabled burst action is ready. Take the **maximum** remaining cooldown over the
enabled burst actions instead. This also silently un-skews two other callers that are
running ~7.5 s early: `chargePoolSeconds` (`:945`) and `apexHoldForBurstSeconds` (`:750`).
That is the explanation for `calibration.md` section E, where `chargePoolSeconds = 35` loses
5.6 Heartbreak casts (-281 DPS, 3.3 sigma) - the effective window at the shipped 25 is
already ~32 s, so 35 becomes ~42 s and outruns the 15 s recharge. **Section E must be
re-swept after this lands.** Check `burstStartable` (`:904`, `nextBurst <= 0.1`) at the
same time: with the maximum form it becomes true only when all three are ready, which is
what the burst actually needs, and the observed cast order is unchanged either way.

*1b.* Give the hold its own key, `empyrealHoldForBurstSeconds = 0`, beside
`chargePoolSeconds` and `apexHoldForBurstSeconds` in `CielBard_Data.lua`, and gate line 958
on it. Empyreal is 260 potency; a 20 % buff window is worth ~52 potency on it, against 260
for the use the hold risks losing. **The hold cannot pay for itself.** Expected:
Empyreal 3.462 -> 3.880/min on the calibration's 520 s normalisation, closing the -12.1 %
count gap to -1.4 %.

**Change 3, as described in `pp_ironjaws_report.md` section 5.** Keep
`dotRefreshSeconds = 3.0` and add an urgency pre-empt immediately after the "establish
missing DoTs" block ending at `:734`, ahead of the proc-consumers: with
`soonest = math.min(ctx.storm, ctx.caustic)`, fire Iron Jaws when
`soonest > 0.2 and soonest <= (c.dotUrgentSeconds or 1.5)` and `ctx.ttk > c.dotMinimumTTK`.
Move `ironJawsEnabled` up from `:760` and add `dotUrgentSeconds = 1.5` to
`CielBard_Data.lua:173`. The `> 0.2` guard stops it firing on a DoT-less target, where Iron
Jaws applies nothing. Expected: Iron Jaws ~12.1, hard casts back to the opener's 1 each,
~1.15 GCDs returned to filler, Caustic Bite uptime 98.65 % -> ~99.9 %, ~+158 potency.
Verify with `--axis "dotUrgentSeconds=0,1.5"`, where 0 must reproduce today's
10.70 / 2.30 / 2.30 exactly.

**Explicitly not recommended:** `maxWeaves = 3` (its +114.4 DPS at 0 ping is t = +1.55 and
**bit-identical to no change at 60 ms ping**, where the third weave cannot clear the 0.65 s
clip guard - a zero-ping artefact); re-ordering the burst priority list (only 0.42 s/fight
is charged to "another oGCD took the slot"); lowering `weaveMinGcdRemaining` (-6.5 / -4.4
DPS) or `requestThrottleMs` or `pulseMs` (all inside noise, none moves a single count);
raising `dotRefreshSeconds` to 6 or 7 (works on the counts, discards DoT duration to do it).

---

## 4. Remaining unverified assumptions

Ordered by how much of the above rests on them. The full list, in the simulator's own
words, is under "Unverified assumptions" in `sim/output/calibration.md` and in
`sim/README.md`.

**Load-bearing for a conclusion here:**

1. **The Repertoire proc model** (corrections item 1: 80 % every 3 s on the song timer from
   42 s remaining down to 3 s, none in the final 3 s, and independent of DoT presence -
   `job.repertoire_independent_of_dots`, default `true`). The Apex sweep produced a sharp
   test of it: the shipped 90 / 35 reproduces the parses' Apex rate to 0.005/min while
   gauge 80 overshoots by 14 %. Either the top 10 were not firing at 80, or **this model
   overstates gauge income by ~12 %**. Item 18 says the event exports cannot decide it.
   The DPS comparison is within-model and unaffected; the *rate* agreement that makes
   change 2 look safe is not. Worth its own investigation - flip
   `repertoire_independent_of_dots` to `false` and re-run the Apex grid.
2. **Apex Arrow's potency floor**: 100 at 20 gauge, linear to 600 at 100. Only the 600
   endpoint is documented. The whole 80-vs-90 result is a trade between cast count and
   curve value, so a different curve could move change 2's sign. Change 1 does not depend
   on it.
3. **The 0.6 s oGCD animation lock.** It is the brief's number; measured MMOMinion gaps in
   `HANDOFF.md` were 640-719 ms including client overhead. 23 % of the Empyreal drift is
   charged to animation lock, so that share is a lower bound and change 1's headroom is
   slightly larger in reality, not smaller.
4. **The linear dummy HP model** (`hp% = 100 * (1 - t / seconds)`) drives the engine's TTK
   bands under `--kill-time`, and therefore every kill-window number in section 1 and the
   whole `terminalDumping` lead in item 4 of the ranking.

**Flagged, not load-bearing here:**

- Army's Muse / Army's Ethos haste table (1 / 2 / 4 / 12 % by stacks, 30 s Ethos
  carry-over) - simulator model, not in any source.
- Barrage's triple hit: `weaponskill_hits = 3` and the `multi_hit_eligible` list are the
  simulator's model; corrections item 8 records only the 30 s Resonant Arrow transform.
  This is what the section 1 scalar move rests on - if the eligibility list is wrong, the
  3.3 % is wrong (the rates are not).
- Barrage's Hawk's Eye guaranteed while every other source rolls 35 %
  (`job.hawks_eye_proc_chance`) - the *scope* of that one knob is the assumption.
- Radiant Encore 700 / 800 / 1100 by coda count (official job guide) against Icy Veins'
  500 / 600 / 900 - flagged, not resolved.
- 30 s Barrage / Radiant Finale transform windows; 20 s Battle Voice, Radiant Finale,
  Raging Strikes - from the guides, not measured on the client.
- Non-DoT status ids are internal to the simulator: self-consistent, unverified against the
  live client.
- Base crit / DH are the merged report's top-10 *event* rates (25.366 % / 28.587 %) with
  the simulator's own buff uptimes deconvolved out; they are not damage-weighted, and the
  parses' external raid buffs are not separable.
- Bloodletter's 130 potency is kept in the tables although the action is trait-upgraded to
  Heartbreak Shot (180) at level 100.

**Structural limits, not assumptions:**

- **Single target, stationary dummy, no downtime, ping 0** for every DPS number above
  except the 60 ms Empyreal re-run. Rain of Death, Ladonsbite and Shadowbite have no
  damage model, so every shared charge becomes a Heartbreak Shot and the cleave
  optimisation cannot be tested. Utility casts are not modelled, which is most of the
  residual 0.658 casts/min against the parses.
- **The scalar absorbs what it should not**: external raid buffs in aDPS, the parses'
  movement and downtime, the potion (measured +1.08 % at 150 seeds, 5.7 sigma - re-fitting
  with `--potion` would drop the scalar ~1.1 % to ~131.0), and Bard auto attacks
  (`stats.auto_attack_dps` ships at 0.0, worth 7-10 % of real aDPS, and absorbed as a
  multiple of potency rather than of time - which biases any experiment that moves GCD
  count or uptime without moving potency).
- **One multiplicative scalar cannot correct a rotation-shape error.** Its mean residual is
  zero by construction and its R^2 against a constant-mean null is 0.029. Judge the
  rotation from the per-action rate table, never from the DPS number.
- **Two SPEC scenarios are unreachable by the shipped engine** and are documented rather
  than papered over (the 150 ms ping oGCD reduction, arithmetically impossible below
  ~350 ms; the potion landing before Raging Strikes on the opener). Their tests are
  `expectedFailure`, so an engine change that satisfies them fails the suite loudly.
