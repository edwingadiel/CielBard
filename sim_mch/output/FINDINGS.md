# CielMachinist 0.2.0 — simulator findings

Measured with `sim_mch` against the shipped engine, 2026-09-19. **Section 0 is the calibration against 40 real parses; read it first.** Sections 1-5 were measured before calibration (scalar 100, assumed Queen timeline); the key sweeps were re-run afterwards and every conclusion held (section 0.4). Unless stated otherwise: one 10% party-buff window of 20 s every 120 s from 0:06, the target dying at the end of the fight, and every point averaged over fight lengths of 300, 360, 420, 480 and 540 s. The rotation is deterministic, so these are exact differences in expected damage, not estimates. DPS is uncalibrated; read the percentages.

## 0. Calibration against the top 40 Machinist parses (Vamp Fatale)

Full report: `calibration.md`. Source: `mch-analysis/output/summary.json` (fights of 501-563 s). Every parse was re-simulated at its own length with the shipped defaults.

### 0.1 The engine presses what the top players press

| per minute | engine | top 10 | difference |
|---|---:|---:|---:|
| all weaponskills | 27.40 | 27.23 | +0.6% |
| Drill | 3.172 | 3.150 | +0.7% |
| Air Anchor | 1.545 | 1.534 | +0.7% |
| Chain Saw, Excavator, Full Metal Field, Wildfire, Barrel Stabilizer | | | 0.0% |
| Heated combo (three actions) | 11.61 | 11.55 | +0.5% |
| Hypercharge | 1.708 | 1.661 | +2.8% |
| Blazing Shot | 8.399 | 8.213 | +2.3% |
| Double Check + Checkmate | 12.91 | 12.69 | +1.7% |
| Reassemble | 1.243 | 1.174 | +5.9% |
| Automaton Queen summons | 1.324 | 1.394 | -5.0% |

- **The opener is identical** to the most common opener in the top 10 (5 of 10): Air Anchor, Drill, Chain Saw, Excavator, Drill, Full Metal Field, Blazing Shot x5, Drill.
- Damage shares agree within about a point everywhere except the combo (engine 21.3%, top 10 19.3%) and the Queen (14.5% vs 15.5%), which is what party buffs do: players' tools and Queen finishers sit under buffs the simulator's scalar spreads evenly.
- The engine's extra Hypercharges and Reassembles are real uses the parses lose to movement and mechanics; the offline engine never moves. Fewer Queen summons is the policy (summon near the cap); battery spent is the same.
- Potions: 24 of 40 parses take the opener (or pre-pull) and 6:00, which is what the engine does; 9 take 2:00 and about 8:00 instead.

### 0.2 One placement differs: Wildfire

Top players press Wildfire a median **1.58 s before** Hypercharge (the double weave ahead of it). The engine presses it about 0.6 s **after**. Both catch six weaponskills; the engine's order was chosen because the offline client showed the early slot dropping the sixth hit without a late weave. Worth revisiting on a live client, where the early placement puts Full Metal Field inside Wildfire.

### 0.3 Fitted values (written to `sim_mch/data`)

- `potency_to_damage` = **111.85** (was an uncalibrated 100), fitted to parse aDPS with auto attacks removed. Residual: mean |error| 0.81%, worst 2.56%. On that scale the engine simulates **1.20% below the top-10 mean**.
- Auto attacks are **6.71%** of a Machinist's damage; the simulator does not model them (`auto_attack_share`).
- **Automaton Queen's measured timeline** replaced the assumed one. In melee range she does five Arm Punches at 6.4 / 8.0 / 9.5 / 11.1 / 12.7 s after the summon, Pile Bunker at 14.7 s and Crowned Collider at 17.5 s: 26.6 potency per battery, matching The Balance. The assumed timeline had her finishers two seconds early (13.0 / 15.5 s). When she is out of range the parses show Roller Dash plus three Arm Punches instead, with the same total.
- While building this, the collector was found to double count pet damage (FFLogs already folds a pet's hits into its owner's stream) and to count the potion buff mirrored onto the Queen. Both are fixed and covered by `tests/test_mch_calibration.py`.

### 0.4 Re-run on the calibrated simulator

Same conditions as below. `queenBatteryOffcycle` 90 (+0.31% over 50), `queenRefillSeconds` 42 (30: -0.18%, 55: -0.30%), `queenTopOffSeconds` 5.5 (+0.14% over 0), `toolHoldSeconds` 0.4 (+0.34%), and heat pooling still loses (**-0.29%**). No default changed.

## 1. Every shipped default is the best value tested

| setting | values (DPS) | verdict |
|---|---|---|
| `toolHoldSeconds` | 0: 35,622 · **0.4: 35,744** | holding the GCD for Air Anchor / Chain Saw is worth **+0.34%** |
| `maxWeaves` | 1: 35,507 · **2: 35,744** | double weaving is worth +0.67% |
| `hyperchargeHoldForBurstSeconds` | 0: 35,632 · **12: 35,744** · 20: 35,744 | keeping Hypercharge for Wildfire: +0.32% |
| `queenBatteryOffcycle` | 50: 35,636 · 70: 35,673 · **90: 35,744** | summon near the cap: +0.30% over summoning at 50 |
| `queenRefillSeconds` | 30: 35,696 · **42: 35,744** · 55: 35,664 | 42 is the peak |
| `chargePoolSeconds` | 0: 35,744 · **15: 35,744** · 30: 35,708 | pooling Double Check / Checkmate changes nothing up to 15 s and costs 0.10% at 30 |
| `reassembleBurstCharges` | 0: 35,710 · **1: 35,744** | +0.10% |
| `reassembleBurstDelaySeconds` | 0: 35,716 · **6: 35,744** | +0.08% |
| `hyperchargeToolLeadSeconds` | 6 = **8** = 10 | no difference: tools fall on GCD boundaries here, so any lead from 6 to 10 s blocks the same windows. Latency jitter would separate them. |

Nothing was changed as a result.

## 2. Heat pooling for a second burst Hypercharge: implemented, shipped Off

`hyperchargeBurstHeat = 45` makes the engine arrive at each two-minute burst with enough heat for a second, heat-funded Hypercharge right behind the free one, as The Balance's static burst does. It works mechanically (two Hypercharges between 2:00 and 2:30 instead of one; covered by the timeline test). It does not pay:

| party-buff window | 300 s | 360 s | 420 s | 480 s | 540 s | mean |
|---|---:|---:|---:|---:|---:|---:|
| 0:06 for 20 s | -1.28% | +0.12% | +0.41% | -0.31% | -0.16% | **-0.24%** |
| 0:10 for 20 s | -1.28% | +0.12% | +0.54% | -0.20% | +0.02% | -0.16% |
| 0:14 for 20 s | -1.22% | +0.20% | +0.61% | -0.14% | +0.07% | -0.10% |
| 0:06 for 30 s | -1.15% | +0.22% | +0.59% | -0.14% | +0.14% | -0.07% |

Without a kill time (a striking dummy, no terminal dump) it is worse, -0.9%: up to 95 heat is still banked when the fight stops.

Why: the free Hypercharge cannot start until Full Metal Field is out and Wildfire is up, about 13 s into the burst, so the second one starts around 0:23 into it and its Blazing Shots land after a 20 s party window has closed. Pooling therefore moves a Hypercharge later without putting it under buffs, and heat that is banked is heat that may never be spent. The sign flips with fight length because it depends on whether the banked heat gets used before the kill.

**Decision:** the feature ships with `hyperchargeBurstHeat = 0`. Set it to 45 in the window ("Heat kept for a second burst Hypercharge") to try it. It would become worthwhile if a live log shows party buffs reliably covering 0:23-0:31 of the burst, or if Wildfire can be pulled earlier.

## 3. Pre-pull

With the engine pulling (`requireCombat` off) the opener becomes Reassemble at -1.7 s, potion at -1.1 s, Air Anchor at 0.0 under Reassemble. The second Reassemble then waits for party buffs and lands on the second Drill at 0:10, which is where The Balance's opener puts it. Armed from the window while waiting for someone else's pull, only Reassemble (and the potion, if enabled) is pressed and the engine never pulls.

## 4. Shape of a six-minute fight at the shipped defaults

`python -m sim_mch.run --seconds 360` (no party buffs, no kill time):

Wildfire 6/6/6 hits · 50 Blazing Shots in 10 Hypercharges · 0 heat and 0 battery wasted · no broken combo · GCD and Air Anchor never idle · Chain Saw idle 4.95 s, all of it the opener's tool order · Queens at 60 / 90 / 90 / 90 / 50 / 100 / 100 battery.

Damage shares: the combo 22.5%, Double Check + Checkmate 13.8%, Drill 13.7%, Automaton Queen 13.6%, Blazing Shot 12.9%, Air Anchor 6.3%, Excavator 4.8%, Full Metal Field 4.4%, Chain Saw 4.4%, Wildfire 3.5%.

## 5. Other checks

- **Ping 0-150 ms:** identical casts and DPS. Two weaves still fit a 2.5 s GCD and one still fits 1.5 s at a 0.75 s lock. This says nothing about request latency on a live client, which the simulator does not model.
- **Targets:** at 3 the engine switches to Scattergun and Bioblaster and keeps Blazing Shot; at 6 it switches to Auto Crossbow. Wildfire stays at 6 hits throughout.

## 6. Still unverified

Everything in HANDOFF.md's "Unverified on a live client" list. The simulator answers the way the engine assumes the client does, so it cannot find an API mismatch.
