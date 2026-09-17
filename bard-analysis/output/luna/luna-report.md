# Luna Bard event analysis

Local-only analysis of 40 cached FFLogs event exports (`output/events/rank-*.json`). Kill-time files were not read or changed.

## Executive findings

- Top 10 mean aDPS 34633.391 vs ranks 21–40 33733.904; this is a result-grouping association, not a causal estimate.
- Top 10 mean cast rate 45.270/min vs 45.275/min; mean GCD rate 25.311/min vs 24.992/min.
- Mean event-level crit rate is 25.366% (top 10) vs 24.639% (21–40); direct-hit rate is 28.587% vs 28.627%. These are RNG-sensitive damage-event proportions.
- Song relaunch gaps average median 42.060 s (top 10) vs 41.325 s; gaps under 40 s are only a screening flag for possible clipping.

## Core action rates (mean casts per 60 seconds)

| Action | Top 10 | Ranks 21–40 | Difference |
|---|---:|---:|---:|
| Burst Shot | 12.916 | 13.253 | -0.336 |
| Refulgent Arrow | 5.850 | 5.791 | 0.059 |
| Heartbreak Shot | 6.553 | 6.969 | -0.416 |
| Empyreal Arrow | 3.935 | 3.911 | 0.024 |
| Iron Jaws | 1.310 | 1.298 | 0.011 |
| Pitch Perfect | 2.812 | 2.778 | 0.034 |
| Apex Arrow | 0.973 | 0.959 | 0.014 |
| Blast Arrow | 0.950 | 0.959 | -0.008 |
| Radiant Encore | 0.579 | 0.578 | 0.001 |
| Sidewinder | 1.042 | 1.045 | -0.002 |

## Burst execution and exact sequences

Each parse has five Raging Strikes/Battle Voice/Radiant Finale cycles in the exported casts (a final partial cycle may exist for very short parses). The JSON preserves exact ordered casts and offsets in a ±4/18-second window around each Raging Strikes cast; `final_burst` and `earlier_burst` are the last and penultimate cycles.

Common final-cycle signatures (top 10):
- 1 parses: `Burst Shot > The Wanderer's Minuet > Burst Shot > Raging Strikes > Burst Shot > Battle Voice > Radiant Finale > Apex Arrow > Barrage > Heartbreak Shot > Refulgent Arrow > Heartbreak Shot > Blast Arrow > Pitch Perfect > Empyreal Arrow > Radiant Encore > Sidewinder > Heartbreak Shot > Resonant Arrow > Pitch Perfect > Burst Shot > Nature's Minne`
- 1 parses: `Burst Shot > The Wanderer's Minuet > Burst Shot > Raging Strikes > Burst Shot > Empyreal Arrow > Refulgent Arrow > Battle Voice > Radiant Finale > Radiant Encore > Barrage > Heartbreak Shot > Apex Arrow > Pitch Perfect > Heartbreak Shot > Blast Arrow > Heartbreak Shot > Refulgent Arrow > Sidewinder > Troubadour > Resonant Arrow > Pitch Perfect > Empyreal Arrow > Iron Jaws`
- 1 parses: `The Wanderer's Minuet > Empyreal Arrow > Refulgent Arrow > Battle Voice > Radiant Finale > Raging Strikes > Radiant Encore > Barrage > Refulgent Arrow > Pitch Perfect > Heartbreak Shot > Apex Arrow > Sidewinder > Heartbreak Shot > Blast Arrow > Second Wind > Resonant Arrow > Heartbreak Shot > Iron Jaws > Pitch Perfect > Empyreal Arrow > Refulgent Arrow > Burst Shot`
- 1 parses: `Burst Shot > Battle Voice > Radiant Finale > Refulgent Arrow > Raging Strikes > Iron Jaws > Empyreal Arrow > Pitch Perfect > Apex Arrow > Heartbreak Shot > Barrage > Blast Arrow > Sidewinder > Heartbreak Shot > Refulgent Arrow > Heartbreak Shot > Troubadour > Resonant Arrow > Radiant Encore > Pitch Perfect > Refulgent Arrow > Empyreal Arrow`
- 1 parses: `Refulgent Arrow > Battle Voice > Radiant Finale > Burst Shot > Raging Strikes > Radiant Encore > Heartbreak Shot > Refulgent Arrow > Barrage > Heartbreak Shot > Refulgent Arrow > Resonant Arrow > Troubadour > Heartbreak Shot > Burst Shot > Pitch Perfect > Empyreal Arrow > Burst Shot > Sidewinder > Pitch Perfect`

Common final-cycle signatures (ranks 21–40):
- 1 parses: `Burst Shot > Radiant Finale > Burst Shot > Battle Voice > Raging Strikes > Burst Shot > Heartbreak Shot > Barrage > Refulgent Arrow > Pitch Perfect > Empyreal Arrow > Radiant Encore > Heartbreak Shot > Apex Arrow > Pitch Perfect > Troubadour > Blast Arrow > Heartbreak Shot > Resonant Arrow > Sidewinder > Burst Shot > Iron Jaws`
- 1 parses: `Refulgent Arrow > Radiant Finale > Battle Voice > Burst Shot > Raging Strikes > Heartbreak Shot > Apex Arrow > Empyreal Arrow > Blast Arrow > Barrage > Sidewinder > Refulgent Arrow > Pitch Perfect > Heartbreak Shot > Radiant Encore > Troubadour > Heartbreak Shot > Resonant Arrow > Iron Jaws > Pitch Perfect > Burst Shot`
- 1 parses: `Burst Shot > Radiant Finale > Battle Voice > Refulgent Arrow > Raging Strikes > Heartbreak Shot > Iron Jaws > Empyreal Arrow > Apex Arrow > Pitch Perfect > Barrage > Refulgent Arrow > Sidewinder > Troubadour > Heartbreak Shot > Radiant Encore > Heartbreak Shot > Blast Arrow > Pitch Perfect > Resonant Arrow`
- 1 parses: `Refulgent Arrow > Radiant Finale > Burst Shot > Battle Voice > Raging Strikes > Apex Arrow > Empyreal Arrow > Pitch Perfect > Refulgent Arrow > Troubadour > Barrage > Blast Arrow > Sidewinder > Heartbreak Shot > Iron Jaws > Heartbreak Shot > Heartbreak Shot > Radiant Encore > Pitch Perfect > Refulgent Arrow > Resonant Arrow > Empyreal Arrow`
- 1 parses: `Refulgent Arrow > Pitch Perfect > Burst Shot > Heartbreak Shot > Raging Strikes > Apex Arrow > Empyreal Arrow > Sidewinder > Radiant Encore > Troubadour > Pitch Perfect > Burst Shot > Barrage > Heartbreak Shot > Resonant Arrow > Heartbreak Shot > Blast Arrow > Iron Jaws > Pitch Perfect > Refulgent Arrow > Empyreal Arrow > Heartbreak Shot`

Observed robust pattern: every cached parse has five Raging Strikes, five Battle Voice, and five Radiant Finale casts. Barrage has one four-cast outlier; exact weave order and late-fight truncation should be judged from per-parse JSON rather than a single canonical sequence.

## Songs, key procs, and outliers

- Song casts average 13.100 per top-10 parse vs 13.250 for ranks 21–40. Under-40-second adjacent-song gaps: 38.910% top 10 vs 41.218% ranks 21–40.
- In the exact final-burst windows, the most common adjacent transitions are `Heartbreak Shot → Blast Arrow` (7 occurrences) for top 10 and `Burst Shot → Radiant Finale` (10) for ranks 21–40; no single full sequence recurs across these 40 exports.
- Apex Arrow, Blast Arrow, and Radiant Encore counts plus nearest-following timing are preserved per parse; compare `key_counts` and `relationships` to study gauge/proc conversion. Event exports do not include gauge values, so missed-opportunity claims are hypotheses.
- Empyreal Arrow, Heartbreak Shot, Iron Jaws, and Pitch Perfect counts/rates are similarly observable. Pitch Perfect count is not a direct measure of repertoire stacks because stacks are not exported.
- Potion events are identifiable when the ability name is exported (mostly `Grade 4 Gemdraught of Dexterity [HQ]`); absence is not proof of no potion because API/event filtering can omit actions.
- Rate outliers are preserved in `outliers`: highest cast-rate parse is rank 23 (46.114/min), lowest is rank 37 (44.083/min); highest and lowest event-level crit-rate parses are ranks 10 (28.753%) and 39 (21.667%).
- The clearest group-level association is slightly higher top-10 GCD rate and crit rate, while total cast rate is virtually identical. That is descriptive; the event export cannot establish whether damage, execution, encounter uptime, or RNG caused rank differences.

## RNG and limitations

- Crit/direct-hit percentages use all exported damage events, including periodic ticks and multi-hit effects; they are not weighted contribution rates. `hitType==2` is treated as critical and the export's `directHit` flag as direct hit.
- Timing is relative to each export's first cast. Cast events show intent/order, not animation-lock completion, slidecast, missed targets, server latency, or exact GCD readiness.
- No gauge/resource state, buff snapshots, party composition, deaths/mechanics, or target uptime is present in these files. Therefore the report distinguishes descriptive recurring patterns from optimization hypotheses.
- Full per-parse details, exact final/earlier sequences, all action counts, damage-event RNG, and outlier identification are in `luna-summary.json`.
