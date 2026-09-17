# Apex timing sweep - `MECHANICS_CORRECTIONS.md` item 16

**Verdict, in one line: the hypothesis wins, by 0.25%.** Firing Apex at 80 gauge with no pre-burst hold beats the shipped 90 / 35 defaults by **+86.7 DPS, +0.254%** over 300 paired seeds (t(299) = +3.67, p = 0.0003, 95% CI +0.12% to +0.39%). The 60-seed grid the sweep was specified at cannot see an effect that small - there it is +0.18%, p = 0.21 - so the grid is reported first and the high-power run that settles it second.

Two qualifications, both of which matter more than the headline:

1. **All of the gain is the gauge threshold; none of it is the hold.** 80 beats 90 at both hold values (+0.20%, p = 0.008 at hold 0; +0.23%, p = 0.003 at hold 35). Dropping `apexHoldForBurstSeconds` from 35 to 0 is worth +0.06% at gauge 90 (p = 0.28) and +0.03% at gauge 80 (p = 0.67) - unmeasurable at 300 seeds.
2. **The reasoning item 16 gives for the hypothesis is contradicted by this sweep even as its conclusion is confirmed.** Item 16 infers "they fired at 80" from the top-10 rate of 0.973 Apex/min. In the simulator, firing at 80 produces 1.106 Apex/min; it is the shipped 90 / 35 that produces 0.969/min and lands on the parse rate. The gauge income the event exports could not show (item 18) is higher than the ~100/min the inference assumed, so the observed rate is evidence *for* the current defaults. The recommendation to change the threshold stands on the DPS measurement alone.

## Method

`apexOffcycleGauge` in {80, 90, 100} x `apexHoldForBurstSeconds` in {0, 15, 35}, 510 s striking dummy, ping 0 ms, pulse 30 ms, seeds 1-60 (60 per point, 540 fights), one fight per seed, single target, no downtime, no potion, no kill time - the dummy never dies, so the engine's terminal band never opens. Five of the nine points were then re-run at 300 seeds.

Both keys are set through the simulator's engine-config override, `FightConfig.engine_config`, which is what `sim.sweep --axis` hands to `CielBardEngine.Init`. Nothing under `CielBard/` was modified and the integration suite's sha256 pins on `CielBard_Data.lua` and `CielBard_Rotation.lua` still hold.

```
"C:\Users\xemna\AppData\Local\Programs\Python\Python312\python.exe" -m sim.sweep \
  --seconds 510 --ping 0 --seeds 1-60 --workers 12 \
  --stat potency_to_damage=132.401588 \
  --axis "apexOffcycleGauge=80,90,100" --axis "apexHoldForBurstSeconds=0,15,35" \
  --csv sim/output/sweep_apex.csv
```

That command was run and its nine rows match the table below to the decimal (`sim/output/sweep_apex.csv`); the analysis below adds the per-seed series, which the sweep CSV does not carry.

Every point runs the same seed list, so any two points are compared **paired**: the per-seed difference cancels the shared damage-roll and tick-offset noise, and its standard error comes out at 18-28 DPS against the 33-35 DPS batch standard errors of the two points it is built from. An unpaired reading of the 300-seed numbers - 34,247.4 +- 35.3 against 34,160.7 +- 32.8 - would call the same difference 1.8 sigma and stop there, which is exactly the trap `sim/README.md` warns about in the other direction. Both are in the tables.

Damage scale: `potency_to_damage = 132.401588`, the fitted scalar in `sim/output/stats.override.json` (`sim/data/stats.json` still ships the uncalibrated 100.0). The scalar is an exact linear multiplier on every damage instance - one fight run at 100.0 and at 132.401588 differs by exactly that factor - so every percentage, t statistic and p value here is identical at either scale.

## The specified grid: 9 points x 60 seeds

| gauge / hold s        |  n | DPS mean | DPS sd | DPS sem | Apex | Blast | Apex+Blast | SV overcap | vs default |     % | paired t |      p |
|-----------------------|---:|---------:|-------:|--------:|-----:|------:|-----------:|-----------:|-----------:|------:|---------:|-------:|
| 90 / 0                | 60 | 34,221.4 |  569.0 |    73.5 | 8.52 |  8.47 |      16.98 |        0.0 |      +62.9 | +0.18 |    +1.55 | 0.1254 |
| 80 / 0 **hypothesis** | 60 | 34,220.9 |  683.0 |    88.2 | 9.45 |  9.40 |      18.85 |        0.0 |      +62.3 | +0.18 |    +1.26 | 0.2125 |
| 100 / 0               | 60 | 34,191.5 |  631.2 |    81.5 | 8.00 |  8.00 |      16.00 |        2.7 |      +33.0 | +0.10 |    +0.53 | 0.5995 |
| 100 / 15              | 60 | 34,191.5 |  631.2 |    81.5 | 8.00 |  8.00 |      16.00 |        2.7 |      +33.0 | +0.10 |    +0.53 | 0.5995 |
| 100 / 35              | 60 | 34,191.5 |  631.2 |    81.5 | 8.00 |  8.00 |      16.00 |        2.7 |      +33.0 | +0.10 |    +0.53 | 0.5995 |
| 80 / 35               | 60 | 34,179.3 |  599.4 |    77.4 | 8.82 |  8.75 |      17.57 |        0.0 |      +20.7 | +0.06 |    +0.39 | 0.6998 |
| 80 / 15               | 60 | 34,166.0 |  667.1 |    86.1 | 9.22 |  9.15 |      18.37 |        0.0 |       +7.4 | +0.02 |    +0.16 | 0.8750 |
| 90 / 15               | 60 | 34,166.0 |  547.6 |    70.7 | 8.43 |  8.37 |      16.80 |        0.0 |       +7.4 | +0.02 |    +0.25 | 0.8012 |
| 90 / 35 **default**   | 60 | 34,158.6 |  522.2 |    67.4 | 8.32 |  8.25 |      16.57 |        0.0 |       +0.0 | +0.00 |    +0.00 | 1.0000 |

Counts are casts per 510 s fight. **SV overcap** is Soul Voice gained above 100 and therefore lost, summed per fight. The counter was already in the simulator - `sim/core.py` increments `wasted["soul_voice_overcap"]` on every gain that would cross `job.soul_voice_max`, it reaches the caller as `FightResult.wasted` and `sim.run` prints it as `waste  soulvoice` - so nothing had to be added for this sweep. `vs default` is the paired difference against the shipped 90 / 35, on 59 degrees of freedom. Rejections and engine warnings: 0 across all 540 fights.

At 60 seeds the hypothesis is **+62.3 DPS, +0.18%** over the default: sd of the paired difference 383.0, standard error 49.4, t(59) = +1.26, p = 0.2125, 95% CI -0.11% to +0.47%. The interval straddles zero, so on the specified grid alone the honest answer is "not shown". Resolving a 0.18% effect at 80% power needs about 297 seeds per point.

## The 300-seed confirmation

Five points re-run at seeds 1-300: the two the question is about, the grid's other leader, and the two that complete a {80, 90} x {0, 35} factorial plus the gauge-100 extreme.

| gauge / hold s        |   n | DPS mean | DPS sd | DPS sem | Apex | Blast | SV overcap | potency | vs default |      % | paired sem |     t |      p |
|-----------------------|----:|---------:|-------:|--------:|-----:|------:|-----------:|--------:|-----------:|-------:|-----------:|------:|-------:|
| 80 / 0 **hypothesis** | 300 | 34,247.4 |  612.1 |    35.3 | 9.40 |  9.33 |       0.00 |  99,275 |      +86.7 | +0.254 |       23.6 | +3.67 | 0.0003 |
| 80 / 35               | 300 | 34,237.7 |  595.8 |    34.4 | 8.79 |  8.73 |       0.00 |  99,309 |      +77.0 | +0.225 |       26.0 | +2.96 | 0.0033 |
| 90 / 0                | 300 | 34,179.8 |  588.7 |    34.0 | 8.45 |  8.39 |       0.00 |  99,178 |      +19.1 | +0.056 |       17.6 | +1.08 | 0.2792 |
| 90 / 35 **default**   | 300 | 34,160.7 |  567.7 |    32.8 | 8.24 |  8.19 |       0.00 |  99,165 |       +0.0 | +0.000 |        0.0 | +0.00 | 1.0000 |
| 100 / 0               | 300 | 34,145.0 |  597.1 |    34.5 | 7.98 |  7.97 |       2.35 |  98,984 |      -15.7 | -0.046 |       26.4 | -0.59 | 0.5538 |

### Decomposition

| comparison                        | A       | B       | A-B DPS |      % | paired sem |     t |      p | 95% CI %         |
|-----------------------------------|---------|---------|--------:|-------:|-----------:|------:|-------:|------------------|
| hypothesis vs default (both axes) | 80 / 0  | 90 / 35 |   +86.7 | +0.254 |       23.6 | +3.67 | 0.0003 | +0.118 .. +0.390 |
| gauge 80 vs 90, hold fixed at 0   | 80 / 0  | 90 / 0  |   +67.6 | +0.198 |       25.2 | +2.69 | 0.0077 | +0.053 .. +0.343 |
| gauge 80 vs 90, hold fixed at 35  | 80 / 35 | 90 / 35 |   +77.0 | +0.225 |       26.0 | +2.96 | 0.0033 | +0.075 .. +0.375 |
| hold 0 vs 35, gauge fixed at 90   | 90 / 0  | 90 / 35 |   +19.1 | +0.056 |       17.6 | +1.08 | 0.2792 | -0.046 .. +0.158 |
| hold 0 vs 35, gauge fixed at 80   | 80 / 0  | 80 / 35 |    +9.7 | +0.028 |       22.7 | +0.43 | 0.6704 | -0.102 .. +0.159 |
| gauge 100 vs default              | 100 / 0 | 90 / 35 |   -15.7 | -0.046 |       26.4 | -0.59 | 0.5538 | -0.198 .. +0.106 |
| gauge 100 vs hypothesis           | 100 / 0 | 80 / 0  |  -102.4 | -0.299 |       28.0 | -3.66 | 0.0003 | -0.460 .. -0.138 |

Read down that table and the structure is unambiguous. The gauge threshold carries the whole effect and carries it at both hold values; the hold carries none of it at either gauge; and gauge 100 is the one clearly bad choice, 0.30% behind the hypothesis (p = 0.0003) although it is statistically indistinguishable from the shipped default.

## Marginals over the 60-seed grid

| apexOffcycleGauge | fights | DPS mean | DPS sem | Apex | Blast | SV overcap |
|-------------------|-------:|---------:|--------:|-----:|------:|-----------:|
| 80                |    180 | 34,188.7 |    48.3 | 9.16 |  9.10 |        0.0 |
| 90                |    180 | 34,182.0 |    40.6 | 8.42 |  8.36 |        0.0 |
| 100               |    180 | 34,191.5 |    46.8 | 8.00 |  8.00 |        2.7 |

| apexHoldForBurstSeconds | fights | DPS mean | DPS sem | Apex | Blast | SV overcap |
|-------------------------|-------:|---------:|--------:|-----:|------:|-----------:|
| 0                       |    180 | 34,211.3 |    46.7 | 8.66 |  8.62 |        0.9 |
| 15                      |    180 | 34,174.5 |    45.8 | 8.55 |  8.51 |        0.9 |
| 35                      |    180 | 34,176.5 |    43.4 | 8.38 |  8.33 |        0.9 |

The marginals are the wrong instrument here and are included only to show why: averaging gauge 80 over its three hold values mixes in the two holds that cost it casts, and averaging hold 0 over its three gauges mixes in gauge 100, where the hold is inert. Both marginal ranges come out under 0.11%, smaller than the paired effect the factorial finds. Use the decomposition table, not these.

## Cast rates against the parse study

Item 16's top-10 rates are 0.973 Apex/min and 0.950 Blast/min, which over 8.50 min are 8.27 Apex and 8.07 Blast per fight.

| gauge / hold s | Apex | Apex/min | vs parses | Blast | Blast/min | vs parses | Blast/Apex % | potency |   GCDs |
|----------------|-----:|---------:|----------:|------:|----------:|----------:|-------------:|--------:|-------:|
| 80 / 0         | 9.45 |    1.112 |    +0.139 |  9.40 |     1.106 |    +0.156 |         99.5 |  99,280 | 214.92 |
| 80 / 15        | 9.22 |    1.084 |    +0.111 |  9.15 |     1.076 |    +0.126 |         99.3 |  99,272 | 214.92 |
| 80 / 35        | 8.82 |    1.037 |    +0.064 |  8.75 |     1.029 |    +0.079 |         99.2 |  99,335 | 214.92 |
| 90 / 0         | 8.52 |    1.002 |    +0.029 |  8.47 |     0.996 |    +0.046 |         99.4 |  99,238 | 214.92 |
| 90 / 15        | 8.43 |    0.992 |    +0.019 |  8.37 |     0.984 |    +0.034 |         99.2 |  99,227 | 214.92 |
| 90 / 35        | 8.32 |    0.978 |    +0.005 |  8.25 |     0.971 |    +0.021 |         99.2 |  99,187 | 214.92 |
| 100 / 0        | 8.00 |    0.941 |    -0.032 |  8.00 |     0.941 |    -0.009 |        100.0 |  98,948 | 214.88 |
| 100 / 15       | 8.00 |    0.941 |    -0.032 |  8.00 |     0.941 |    -0.009 |        100.0 |  98,948 | 214.88 |
| 100 / 35       | 8.00 |    0.941 |    -0.032 |  8.00 |     0.941 |    -0.009 |        100.0 |  98,948 | 214.88 |

The shipped 90 / 35 reproduces the parses to 0.005 Apex/min and 0.021 Blast/min. The hypothesis's 80 / 0 fires 14% more Apex than the top 10 did. Item 16 reasoned from roughly 100 Soul Voice per minute of income that about one Apex per minute implies an 80 threshold; the simulator's income is higher than that, so one Apex per minute is what 90-with-the-hold produces and an 80 threshold would have shown up in the logs as 1.1/min. Either the parses were not firing at 80, or the simulator's Repertoire model (80% every 3 s on the song timer, corrections item 1, still flagged as an assumption) overstates gauge income by about 12%. Item 18 says the exports cannot tell us which; this is the sharpest test of that assumption the sim has produced so far and it is worth its own investigation.

Blast follows Apex 99.2-100% of the time at every point, so the Blast column carries no independent information: nothing here ever strands a Blast Arrow.

## Why the effect is only a quarter of a percent

Three mechanisms very nearly cancel.

1. **The GCD count never changes.** 214.88 weaponskills per fight at every one of the five 300-seed points. An extra Apex+Blast pair adds no casts, it *displaces* two fillers - a Burst Shot at 220 potency or a Refulgent Arrow at 280.
2. **Apex's potency curve pays for most of the casts you give up.** `job.json` is linear from 100 potency at 20 gauge to 600 at 100, so Apex is 475 at 80 gauge, 537 at 90 and 600 at 100, with a flat 600 Blast Arrow behind any of them. Net gain over the ~245-potency filler a pair replaces: about 585 at 80 gauge, 647 at 90, 710 at 100. Multiply by the pairs each policy gets (9.40, 8.24, 7.98) and you get 5,500, 5,330 and 5,670 - a 6% spread on a term that is itself 5.5% of the fight. The measured per-fight potency totals bear it out: 99,275 for 80 / 0 against 99,165 for 90 / 35, a paired **+109.6 potency, +0.110%** (t(299) = +4.38, p < 0.0001). That is about half of the +0.254% DPS; the rest is that the extra pairs fall inside Raging Strikes and Battle Voice more often than the filler they replace. At these error bars the split is resolved only roughly.
3. **Soul Voice overcap is zero below a 100 threshold.** Not small - zero, in all 900 fights run at gauge 80 and 90 across both sample sizes. Only the gauge-100 policy overcaps, and only by 2.35 Soul Voice per fight: half a Repertoire proc, 0.03 of an Apex, 0.3% of the roughly 800 gauge a fight spends. The overcap penalty item 16 expects from holding is real and far too small to be the mechanism. What gauge 100 actually costs is 1.42 fewer Apex+Blast pairs than the hypothesis, and that is worth the measured -0.30%.

One structural oddity worth recording: **`apexHoldForBurstSeconds` is completely inert at gauge 100.** The three gauge-100 rows of the 60-seed grid are not close, they are identical to the last damage event. `CielBard_Rotation.lua` gates the hold on `ctx.soulVoice < 95`, and a policy that only fires at 100 is never below 95 when it wants to fire, so the branch is unreachable. Any future sweep that crosses `apexOffcycleGauge` above 95 with the hold is spending two thirds of its fights measuring nothing.

## Recommendation

- **Change `apexOffcycleGauge` from 90 to 80.** +0.20% to +0.23% depending on the hold, p < 0.01 both ways, consistent in sign at every sample size run here. It is a small gain but it is a real one and it costs nothing.
- **Leave `apexHoldForBurstSeconds` alone, or drop it for simplicity, not for DPS.** Neither 0 nor 15 nor 35 is distinguishable from the others at 300 seeds. If it is removed, the defensible claim is "one fewer rule, no measured cost", not a DPS gain. Note that it is not a free deletion: it shares `resourcePooling` with the Empyreal Arrow hold and `chargePoolSeconds`, so a change should be made on its own key.
- **Do not raise the threshold to 100.** It is the worst of the three gauges, -0.30% against the hypothesis, and it disables the hold as a side effect.
- **Before either change, settle the Empyreal Arrow hold.** `sim/output/calibration.md` measures that one at +0.80%, three times everything in this sweep, and it lives behind the same `resourcePooling` switch.

## What is not settled

- **One fight shape only.** 510 s, single target, 0 ping, striking dummy, no potion, no downtime, no kill time. The pre-burst hold exists to protect the two-minute window; a fight that ends inside a burst, or a `--kill-time` fight where the terminal band opens and `apexThreshold` drops to 20, can weight placement differently. Multi-target was not touched at all.
- **The Repertoire model is load-bearing for the rate comparison.** Gauge income is what converts a threshold into a cast count, and that income rests on corrections item 1 (80% every 3 s on the song timer) and on `repertoire_independent_of_dots`, both flagged assumptions. The DPS result is a within-model comparison and is unaffected; the disagreement with the parse rate is not.
- **Ping 0 was specified and used.** The engine's weave arithmetic changes with ping (`sim/README.md`, mismatch 8.2 #20), and Apex competes for the same GCD slots, so a 150 ms re-run is cheap insurance before shipping a threshold change.

## Reproducing

Raw per-seed series - DPS, Apex, Blast, Soul Voice overcap, Repertoire overcap, GCD count, total potency - are in `sim/output/sweep_apex.json` (9 points x 60 seeds), `sim/output/sweep_apex_confirm.json` (80/0, 90/0, 90/35 x 300 seeds) and `sim/output/sweep_apex_confirm2.json` (80/35, 100/0 x 300 seeds). All of them were produced by `sim.batch.run_batch` with the two keys carried in `FightConfig.engine_config`, the same override path `sim.sweep --axis` uses; the `sim.sweep` command line at the top of this report reproduces the grid directly.
