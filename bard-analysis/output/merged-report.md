# Vamp Fatale Bard Optimization — Top-40 FFLogs Analysis

## Bottom line

The top Bard parses are not distinguished by a secret fixed rotation. The strongest repeatable signals are:

1. **More GCD throughput**, not more total button presses.
2. **More deliberate song allocation**: longer Wanderer's Minuet and Mage's Ballad sections, with Army's Paeon clipped earlier.
3. **Better multi-target charge conversion**: more Rain of Death in place of Heartbreak Shot when cleave is available.
4. **A favorable final kill window**, especially a boss death roughly 20–30 seconds after the final Battle Voice/Radiant Finale window begins.
5. **Some additional crit luck**, but not enough to explain the ranking gap by itself.

The correct model is therefore a priority system with encounter- and time-to-kill-aware branches, not a single memorized cast string.

## Dataset

- Encounter: Vamp Fatale, encounter 101, zone 73.
- Forty highest Bard aDPS rankings returned by FFLogs at collection time.
- Every report/fight/Bard actor resolved successfully.
- Source-filtered Casts and DamageDone timelines were analyzed locally.
- Top 10 were compared with ranks 21–40; ranks 11–20 remain in the full-population statistics.
- Kill timing was measured against the Bard's actual final Battle Voice/Radiant Finale casts.

## What separates the top group

| Metric | Top 10 | Ranks 21–40 | Interpretation |
|---|---:|---:|---|
| Mean aDPS | 34,633 | 33,734 | About 899 aDPS apart |
| All casts/min | 45.270 | 45.275 | Essentially identical |
| GCDs/min | **25.311** | **24.992** | Top group gains about 0.32 GCD/min |
| Median GCD interval | 2.490s | 2.488s | Gear/GCD speed is not the explanation |
| Crit-event rate | 25.366% | 24.639% | Top group had +0.73 percentage points |
| Direct-hit rate | 28.587% | 28.627% | Effectively identical |
| Potion-use rate | 100% | 100% | Necessary baseline, not a differentiator |

Across all 40 parses, aDPS correlated more strongly with GCD rate (`r ≈ 0.30`) than with crit-event rate (`r ≈ 0.12`), total cast rate (`r ≈ 0.04`), direct-hit rate (`r ≈ -0.07`), or death-after-final-buff timing alone (`r ≈ -0.08`). These are descriptive correlations within an already-selected elite sample, not causal estimates.

At the observed average fight duration, the GCD-rate difference is worth roughly **2.7 additional GCDs per fight**. The players are not weaving materially more abilities; they are losing fewer GCD opportunities.

## Empirical song cycle

Separating song transitions reveals a clearer pattern than treating every sub-40-second gap as clipping:

| Transition | Top 10 mean | Ranks 21–40 mean | Top-group behavior |
|---|---:|---:|---|
| Wanderer's Minuet → Mage's Ballad | **43.84s** | 43.31s | Holds Wanderer's about 0.54s longer |
| Mage's Ballad → Army's Paeon | **42.27s** | 41.34s | Holds Mage's about 0.93s longer |
| Army's Paeon → Wanderer's Minuet | **34.91s** | 36.23s | Clips Army's about 1.32s earlier |

This supports the optimized song philosophy: extract more value from Wanderer's and Mage's, then shorten Army's to return to Wanderer's on the two-minute cycle. It is one of the cleanest actionable differences in the dataset.

## Burst windows

Every one of the 40 parses used exactly five Raging Strikes, five Battle Voices, five Radiant Finales, and five Radiant Encores. This is the non-negotiable backbone.

There was **no repeated universal full burst string**. Proc availability, Soul Voice, song state, mechanics, and kill time changed the exact ordering. Across the top group, the main burst tools were consistently present, but Apex Arrow, Blast Arrow, Radiant Encore, Empyreal Arrow, Pitch Perfect, Barrage, Resonant Arrow, and Iron Jaws moved within the window.

Useful full-fight reference counts for an approximately 8½-minute kill:

| Action | Top-10 mean count |
|---|---:|
| Raging Strikes / Battle Voice / Radiant Finale | 5 each |
| Radiant Encore | 5.0 |
| Barrage | 5.0 |
| Empyreal Arrow | 34.0 |
| Apex Arrow | 8.4 |
| Blast Arrow | 8.2 |
| Heartbreak Shot | 56.6 |
| Iron Jaws | 11.3 |
| Pitch Perfect | 24.3 |

Rank 31 was the notable cooldown-loss outlier with only four Barrage casts. A solver should treat lost major uses as a higher-priority failure than small within-window ordering differences.

## Multi-target nuance

The top group used fewer Heartbreak Shots but more Rain of Death:

| Shared-charge action | Top 10 / min | Ranks 21–40 / min |
|---|---:|---:|
| Heartbreak Shot | 6.553 | 6.969 |
| Rain of Death | **0.831** | **0.488** |
| Combined | 7.384 | 7.457 |

The combined charge-spender rate is nearly the same. The important difference is **where the charge was converted**: top players selected the AoE version more often when additional targets made it profitable. Their Ladonsbite and Shadowbite rates were also higher. This appears to be encounter-specific cleave optimization, not Heartbreak Shot underuse.

## Kill-time result

Using the actual final Battle Voice/Radiant Finale casts:

- Median boss death: **22.03 seconds after the final buff anchor**.
- Range: 8.34–78.31 seconds.
- Twenty-seven of forty kills occurred within 30 seconds of the final anchor.

| Death after final buff anchor | Parses | Mean aDPS |
|---|---:|---:|
| Under 20s | 14 | 33,927.7 |
| **20–30s** | **13** | **34,240.3** |
| Over 30s | 13 | 34,074.4 |

Five of the top ten landed in the 20–30-second band, versus four of ranks 21–40. The first-, second-, and fourth-ranked parses ended 20.81s, 22.20s, and 20.35s after their final anchors.

This supports 20–30 seconds as a favorable **full-burst completion band**: the complete party-buff window contributes to the numerator, with little low-output time afterward. Kill time is meaningful but not sufficient; rank 3 still performed exceptionally with a 39.22-second tail.

## Recommended conditional policy

### Stable backbone

- Never lose a two-minute use that the encounter permits.
- Maintain uninterrupted GCD execution; this was the clearest execution-level group difference.
- Use the empirical song allocation as the default: approximately 43–44s Wanderer's, 42–43s Mage's, and 34–35s Army's.
- Preserve five Barrage/Encore/two-minute cycles at this kill length.
- Choose Rain of Death over Heartbreak Shot whenever the target count makes it a potency gain.
- Treat the burst as a priority set, not a fixed sequence. Proc and gauge state should choose the ordering.

### Expected death under 20 seconds after final buffs

- Front-load the highest available potency immediately.
- Spend Soul Voice, Pitch Perfect stacks, Bloodletter/Heartbreak charges, and available procs without preserving long-term efficiency.
- Do not schedule a late Iron Jaws unless its immediate snapshot/tick value beats a direct GCD before death.
- Move Apex → Blast and Encore earlier if leaving them in the normal position risks losing them.

### Expected death 20–30 seconds after final buffs

- This is the preferred complete-window branch.
- Enter with resources pooled without overcapping.
- Fit the complete Raging/Battle Voice/Finale package and all once-per-window attacks.
- Empty remaining short-cooldown charges after the buff window because there is no meaningful future hold.

### Expected death 31–60 seconds after final buffs

- Perform the complete burst, but retain a sustainable post-burst priority.
- Avoid sacrificing earlier off-cycle Apex/Blast or charge uses merely to make the final window look fuller.
- Refresh DoTs according to realized remaining duration rather than automatically treating the burst as the end of the encounter.

### Expected death more than 60 seconds after final buffs

- Plan the extended tail explicitly: additional Empyreal Arrow, shared-charge, song-proc, DoT, and potential Apex/Blast opportunities matter.
- Do not use a terminal-dump policy immediately after the two-minute window.

## What the eventual solver should score

1. Lost GCD opportunity.
2. A lost major cooldown use before encounter end.
3. Resource overcap or an unspent proc at death.
4. Buff-window potency placement.
5. Correct song-transition timing.
6. Multi-target replacement decisions.
7. DoT refresh value under estimated time to kill.
8. Only then, small ordering differences among otherwise equivalent burst actions.

The kill-time input should be probabilistic—a range or confidence-weighted estimate—not a perfectly known countdown. The policy can compare expected potency for `death <20s`, `20–30s`, `31–60s`, and `>60s` branches and switch only when the advantage exceeds a stability threshold.

## Limitations

- Gauge values, proc-stack state, animation locks, latency, exact target availability, and party buff timelines beyond the Bard's own buffs were not reconstructed.
- Event-level crit rates count periodic and multi-hit damage events equally; they are not damage-weighted crit contribution.
- Higher AoE-action usage strongly suggests cleave optimization but needs target-level damage analysis to price the exact gain.
- The dataset is top-40-selected, so correlations are compressed and should not be generalized to average players.
- Exact sequence diversity means that copying one rank-one string would be less reliable than implementing the priority and conditional rules above.
