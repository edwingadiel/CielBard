# Apex timing sweep - re-run on the Patch 7.5 potency curve (engine 0.5.2)

**Verdict, in one line: 80 still beats 90, and it is no longer close.** On the corrected
140-700 Apex curve, firing Apex at 80 gauge with no pre-burst hold beats 90 gauge by
**+81.0 DPS, +0.237%** over 300 paired seeds (t(299) = +4.00, **p = 0.000079**, 95% CI
**+0.121% to +0.354%**), and beats the pre-0.5.1 shipped 90 / 35 by **+88.9 DPS, +0.260%**
(t(299) = +4.21, p = 0.000034, CI +0.139% to +0.382%). The shipped default is already
`apexOffcycleGauge = 80`; this run confirms the 0.5.1 change under the corrected data
instead of the data it was originally measured on.

**Recommended defaults after this run: `apexOffcycleGauge = 80`, and
`apexHoldForBurstSeconds` moved from 35 to 0.** The gauge threshold is settled. The hold is
the one open question: 80 / 0 beats the shipped 80 / 35 by +43.7 DPS, +0.128%, which lands
exactly on the 5% line (t(299) = +1.95, **p = 0.0524**, CI **-0.001% to +0.257%**). That is
not a significant result at 300 seeds, so the recommendation rests on the fact that the
point estimate is positive at both gauges, that the hold has never once measured positive
in any run of this sweep, and that zero is also the simpler default - not on this
p-value. **No engine file was edited by this pass**; the recommendation is reported for the
maintainer to apply.

One result did change sign from the pre-correction run: **gauge 100 is no longer the worst
point.** It was -0.30% against 80 / 0 on the old curve; here it is -0.100% and not
distinguishable from it (p = 0.156), and it beats gauge 90 (+0.138%, p = 0.048). The
reason is arithmetic - see *Why the ranking moved* below.

## Method

`apexOffcycleGauge` in {80, 90, 100} x `apexHoldForBurstSeconds` in {0, 35}, six points,
**300 paired seeds each (1800 fights)**, 510 s striking dummy, ping 0 ms, pulse 30 ms,
single target, no downtime, no potion, no kill time - the dummy never dies, so the engine's
terminal band never opens. **0 rejections and 0 engine warnings across all 1800 fights.**

- **Engine 0.5.2**, the shipped Lua unmodified. Both keys are set through the simulator's
  engine-config override (`FightConfig.engine_config`, the path behind `sim.sweep --axis`),
  which is what `CielBardEngine.Init` receives. Nothing under `CielBard/` was touched and
  the sha256 pins in `tests/test_integration.py` still hold.
- **Patch 7.5 potencies**: Apex Arrow 140 at 20 gauge rising linearly to 700 at 100, Blast
  Arrow 700 (50% less after the first target), Resonant Arrow 640 (same falloff), Refulgent
  Arrow 280 and 840 under Barrage, Shadowbite 200 and 300 under Barrage, Radiant Encore
  700 / 800 / 1100, Heavy Shot 160.
- **Damage scale**: `potency_to_damage = 128.559424`, the scalar refitted in this pass
  (`sim/output/calibration.md`, seeds 1-150). The scalar is an exact linear multiplier on
  every damage instance, so every percentage, t statistic and p value below is identical at
  any scale.

Every point runs the same seed list, so any two points are compared **paired**: the
per-seed difference cancels the shared damage-roll and proc-timing noise. Its standard
error comes out at 17-26 DPS against the 32-34 DPS batch standard errors of the two points
it is built from - an unpaired reading of 80 / 0 against 90 / 35 (34,202.7 +- 32.2 against
34,113.8 +- 33.7) would call that 1.9 sigma and stop, which is the trap `sim/README.md`
warns about.

## The grid: 6 points x 300 seeds

| gauge / hold s          |   n | DPS mean | DPS sd | DPS sem | Apex | Blast | Apex+Blast | Apex /min | SV overcap | potency |
|-------------------------|----:|---------:|-------:|--------:|-----:|------:|-----------:|----------:|-----------:|--------:|
| **80 / 0 (recommended)**| 300 | 34,202.7 |  557.8 |    32.2 | 9.57 |  9.53 |      19.10 |     1.126 |       0.00 | 102,350 |
| 100 / 0                 | 300 | 34,168.6 |  549.0 |    31.7 | 7.96 |  7.96 |      15.92 |     0.936 |       2.65 | 102,129 |
| 100 / 35                | 300 | 34,168.6 |  549.0 |    31.7 | 7.96 |  7.96 |      15.92 |     0.936 |       2.65 | 102,129 |
| **80 / 35 (shipped)**   | 300 | 34,158.9 |  589.2 |    34.0 | 9.07 |  9.03 |      18.10 |     1.067 |       0.00 | 102,283 |
| 90 / 0                  | 300 | 34,121.6 |  577.0 |    33.3 | 8.64 |  8.60 |      17.24 |     1.016 |       0.00 | 102,232 |
| 90 / 35 (pre-0.5.1)     | 300 | 34,113.8 |  583.6 |    33.7 | 8.41 |  8.37 |      16.78 |     0.990 |       0.00 | 102,209 |

Counts are casts per 510 s fight. **SV overcap** is Soul Voice gained above 100 and
therefore lost, summed per fight (`FightResult.wasted["soul_voice_overcap"]`, printed by
`sim.run` as `waste soulvoice`). GCD count is **214.69-214.70 at every point** - the grid
moves what the GCDs are, never how many there are.

The gauge-100 rows are bit-identical because `CielBard_Rotation.lua` gates the hold on
`ctx.soulVoice < 95`: at a threshold of 100 the hold can never be evaluated. Any future
sweep that crosses gauge > 95 with a hold axis wastes those points.

## Paired comparisons, all 300 seeds

| comparison | diff DPS | % | sd of diff | sem | t(299) | p | 95% CI |
|---|---:|---:|---:|---:|---:|---:|---|
| **80 / 0 vs 90 / 0** | **+81.0** | **+0.237** | 350.6 | 20.2 | **+4.00** | **0.000079** | **+0.121% to +0.354%** |
| **80 / 0 vs 90 / 35** | **+88.9** | **+0.260** | 365.5 | 21.1 | **+4.21** | **0.000034** | **+0.139% to +0.382%** |
| 80 / 35 vs 90 / 35 | +45.1 | +0.132 | 356.7 | 20.6 | +2.19 | 0.0292 | +0.014% to +0.251% |
| **80 / 0 vs 80 / 35** | +43.7 | +0.128 | 388.9 | 22.5 | +1.95 | **0.0524** | -0.001% to +0.257% |
| 90 / 0 vs 90 / 35 | +7.8 | +0.023 | 291.3 | 16.8 | +0.47 | 0.6416 | -0.074% to +0.120% |
| 100 / 0 vs 90 / 0 | +46.9 | +0.138 | 409.5 | 23.6 | +1.99 | 0.0480 | +0.001% to +0.274% |
| 100 / 0 vs 90 / 35 | +54.8 | +0.161 | 425.8 | 24.6 | +2.23 | 0.0266 | +0.019% to +0.302% |
| 80 / 0 vs 100 / 0 | +34.1 | +0.100 | 414.9 | 24.0 | +1.42 | 0.1558 | -0.038% to +0.238% |
| 100 / 0 vs 80 / 35 | +9.6 | +0.028 | 449.9 | 26.0 | +0.37 | 0.7107 | -0.121% to +0.178% |

**Decomposition over the {80, 90} x {0, 35} factorial:**

- gauge **80 vs 90**: +0.237% at hold 0 (p = 0.00008), +0.132% at hold 35 (p = 0.029).
  **The gauge carries the effect at both hold values, and the question the review asked is
  answered: 80 still beats 90 under the 140-700 curve, with a 95% CI that excludes zero by
  a comfortable margin.**
- hold **0 vs 35**: +0.128% at gauge 80 (p = 0.052), +0.023% at gauge 90 (p = 0.64), and
  exactly 0 at gauge 100 where it is unreachable. **The hold is worth between nothing and a
  tenth of a percent.** It is positive in sign at every gauge it can act on and has never
  measured negative, which is why 0 is recommended, but it is not a significant result and
  it should not be reported as one.

Potency moves the same way and rather more cleanly, because potency does not carry the
crit/DH variance: 80 / 0 against 90 / 0 is **+118.1 potency, +0.116%, t = +4.70,
p < 0.00001**; against 90 / 35 it is +141.0 (+0.138%, t = +5.12); against 80 / 35 it is
+66.8 (+0.065%, t = +2.19, p = 0.029). Roughly half of the DPS gain is raw potency; the
rest is the extra Apex+Blast pairs landing inside Raging Strikes and Battle Voice.

## Why the ranking moved

The old (pre-Patch-7.5) curve in the simulator was 100 at 20 gauge to 600 at 100, so an
Apex fired at 80 gauge was worth 475 - **79.2%** of a full-gauge Apex. The corrected curve
is 140 to 700, so the same Apex is worth 560 - **80.0%**. Firing early costs relatively
less than the old tables said, which is why the 80-over-90 margin widened from +0.198% to
+0.237% at hold 0.

The same arithmetic lifts gauge 100 off the bottom. Its penalty was never the Soul Voice
overcap - 2.65 gauge per fight is 0.3% of the roughly 800 gauge a fight spends - it is the
**3.18 fewer Apex+Blast pairs** (15.92 against 19.10). Each pair it does fire is now worth
a larger fraction of the extra pairs 80 gets, so the deficit shrank from -0.30% to -0.100%,
which 300 seeds cannot separate from zero. **Gauge 90 is now the worst of the three**, and
that is the one ordering that is stable: it loses to 80 at both hold values and to 100
(p = 0.048).

**The cast-rate check still disagrees with the DPS result, and by more than before.** The
top-10 parses run 0.973 Apex/min. On engine 0.5.2, gauge 90 / 35 produces 0.990/min - the
closest match - while the recommended 80 / 0 produces **1.126/min, 16% above the parse
rate** (it was 14% before the corrections). So either the top 10 were not firing at 80, or
the simulator's Repertoire/gauge-income model overstates income by roughly 12-14%. That is
`MECHANICS_CORRECTIONS.md` item 1, which item 18 says the surviving event exports cannot
decide. The DPS comparison here is within-model and unaffected by a uniform income error;
the *rate* agreement that would independently corroborate gauge 80 is not. This remains the
sharpest open test of the proc model.

## What this does not show

- Single target, stationary, ping 0, no downtime, no potion, no kill window. The terminal
  TTK band never opens, so nothing here speaks to the end of a fight.
- The Apex potency floor (140 at 20 gauge, linear) is still a simulator assumption; only
  the 700 endpoint is documented. The whole 80-vs-90 result is a trade between cast count
  and curve value, so a differently-shaped curve could move it again - as the last
  correction just demonstrated.
- 80 / 0 against 80 / 35 is p = 0.052 at 300 seeds. Resolving a 0.128% effect at 80% power
  needs about 590 seeds per point; that run has not been made.

## Reproduce

The grid is exactly what this `sim.sweep` invocation evaluates:

```
"C:\Users\xemna\AppData\Local\Programs\Python\Python312\python.exe" -m sim.sweep \
  --seconds 510 --ping 0 --seeds 1-300 --workers 12 \
  --stat potency_to_damage=128.559424 \
  --axis "apexOffcycleGauge=80,90,100" --axis "apexHoldForBurstSeconds=0,35" \
  --csv sim/output/sweep_apex.csv
```

`sim.sweep` reports batch means and standard errors only, and the paired differences,
t statistics, p values and confidence intervals above need the per-seed series. This pass
therefore drove `sim.batch.run_batch` directly - the same function `sim.sweep` calls, with
the same `FightConfig` and the same seed list per point - and kept the per-seed DPS and
potency each batch returns. `sim/output/sweep_apex.csv` is written from those batches in
`sim.sweep --csv` column order, so it is the table the command above would produce.
