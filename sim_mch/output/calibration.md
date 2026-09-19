# sim_mch calibration

40 parses, fight length 501-563 s. Each was re-simulated at its own length with the shipped engine defaults, the target dying at the end, the parse's potion count, and the engine pulling.

## 1. Damage scalar

- fitted `potency_to_damage` = **111.8541** (was 111.8541)
- auto attacks are 6.71% of parse damage; they are removed from the target because the simulator does not model them (`auto_attack_share` in stats.json)
- residual: mean |error| 0.79%, worst -2.52%
- engine vs top-10 mean: -1.20% (by construction the all-parse mean is 0; this is the top-10 slice)

The scalar absorbs everything that is not rotation: gear, party buffs received, real movement and downtime. Judge the rotation from the tables below, never from this number.

## 2. Casts per minute

| action | engine | top 10 | all parses | engine vs top 10 |
|---|---:|---:|---:|---:|
| Heated Split Shot | 3.916 | 3.904 | 3.909 | +0.3% |
| Heated Slug Shot | 3.870 | 3.835 | 3.849 | +0.9% |
| Heated Clean Shot | 3.823 | 3.811 | 3.809 | +0.3% |
| Drill | 3.172 | 3.150 | 3.140 | +0.7% |
| Air Anchor | 1.545 | 1.534 | 1.534 | +0.7% |
| Chain Saw | 1.046 | 1.046 | 1.040 | -0.0% |
| Excavator | 1.046 | 1.046 | 1.040 | -0.0% |
| Full Metal Field | 0.581 | 0.581 | 0.569 | -0.0% |
| Blazing Shot | 8.399 | 8.213 | 8.260 | +2.3% |
| Hypercharge | 1.708 | 1.661 | 1.663 | +2.8% |
| Wildfire | 0.581 | 0.581 | 0.575 | -0.0% |
| Barrel Stabilizer | 0.581 | 0.581 | 0.572 | -0.0% |
| Reassemble | 1.243 | 1.174 | 1.155 | +5.9% |
| Double Check | 6.483 | 6.343 | 6.362 | +2.2% |
| Checkmate | 6.425 | 6.343 | 6.365 | +1.3% |
| Automaton Queen | 1.324 | 1.394 | 1.353 | -5.0% |
| Queen Overdrive | 0.012 | 0.012 | 0.020 | -0.0% |
| all weaponskills | 27.399 | 27.227 | 27.192 | +0.6% |

## 3. Hypercharge and Wildfire

- parses: 98.8% of Hypercharges hold five Blazing Shots (mean 4.98); the engine always fits five offline
- parses: Wildfire lands a median -1.58 s from the nearest Hypercharge (positive = after it); the engine weaves it about +0.6 s after
- potions per parse: 1.95

## 4. Opener

- most common first 12 weaponskills in the top 10 (5 of 10): Air Anchor, Drill, Chain Saw, Excavator, Drill, Full Metal Field, Blazing Shot, Blazing Shot, Blazing Shot, Blazing Shot, Blazing Shot, Drill
- engine: Air Anchor, Drill, Chain Saw, Excavator, Drill, Full Metal Field, Blazing Shot, Blazing Shot, Blazing Shot, Blazing Shot, Blazing Shot, Drill

## 5. Damage shares (auto attacks excluded)

| source | engine | top 10 |
|---|---:|---:|
| Automaton Queen | 14.49% | 15.45% |
| Wildfire | 4.02% | 3.97% |
| Drill | 13.28% | 13.20% |
| Blazing Shot | 12.61% | 12.39% |
| Double Check + Checkmate | 13.46% | 13.66% |
| Heated combo | 21.26% | 19.31% |
| Air Anchor | 6.82% | 6.15% |
| Chain Saw + Excavator | 8.98% | 9.67% |
| Full Metal Field | 5.08% | 5.93% |

## 6. Automaton Queen hit timeline

| # | measured hit | seconds after summon | simulator assumed |
|---:|---|---:|---|
| 1 | Arm Punch | 6.37 | Arm Punch at 6.37 |
| 2 | Arm Punch | 7.97 | Arm Punch at 7.97 |
| 3 | Arm Punch | 9.53 | Arm Punch at 9.53 |
| 4 | Arm Punch | 11.09 | Arm Punch at 11.09 |
| 5 | Arm Punch | 12.65 | Arm Punch at 12.65 |
| 6 | Pile Bunker | 14.74 | Pile Bunker at 14.74 |
| 7 | Crowned Collider | 17.46 | Crowned Collider at 17.46 |

Measured sequence totals 26.6 potency per battery (The Balance: 26.6).

## 7. Queen summon times, top parse

14, 69, 119, 140, 184, 244, 267, 309, 363, 385, 425, 484, 507 s

engine at that length: 9 (60), 68 (90), 121 (90), 176 (90), 197 (50), 246 (100), 306 (100), 363 (90), 401 (90), 431 (50), 483 (90), 508 (50) s (battery)
