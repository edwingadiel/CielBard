# CielMachinist 0.2.0 — simulator findings

Measured with `sim_mch` against the shipped engine, 2026-09-19. Unless stated otherwise: one 10% party-buff window of 20 s every 120 s from 0:06, the target dying at the end of the fight, and every point averaged over fight lengths of 300, 360, 420, 480 and 540 s. The rotation is deterministic, so these are exact differences in expected damage, not estimates. DPS is uncalibrated; read the percentages.

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
