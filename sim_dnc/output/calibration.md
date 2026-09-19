# sim_dnc calibration

40 parses, fight length 499-545 s. Each was re-simulated at its own length with the shipped engine defaults, the target dying at the end, the parse's potion count and the engine pulling, on 4 seeds.

## 1. Ally Esprit chance

Top-10 Saber Dance + Dance of the Dawn: **4.173 per minute**. Simulated rate by chance:

| chance | spenders per minute |
|---:|---:|
| 0.10 | 3.262 |
| 0.15 | 3.623 |
| 0.20 | 4.042 |
| 0.25 | 4.574 |
| 0.30 | 4.775 |

Fitted `ally_esprit.chance` = **0.212** (community estimate: about 0.20).

## 2. Damage scalar

- fitted `potency_to_damage` = **117.5858** (was 100.0)
- auto attacks are 9.95% of parse damage and are removed from the target
- residual: mean |error| 0.96%, worst -4.10%
- engine vs top-10 mean: -1.36%

The scalar absorbs gear, party buffs received and real downtime. Judge the rotation from the tables below.

## 3. Casts per minute

| action | engine | top 10 | all parses | engine vs top 10 |
|---|---:|---:|---:|---:|
| Cascade | 3.547 | 3.327 | 3.370 | +6.6% |
| Fountain | 3.321 | 3.221 | 3.154 | +3.1% |
| Reverse Cascade | 2.771 | 2.587 | 2.551 | +7.1% |
| Fountainfall | 2.681 | 2.467 | 2.561 | +8.6% |
| Saber Dance | 3.670 | 3.585 | 3.556 | +2.4% |
| Dance of the Dawn | 0.552 | 0.588 | 0.585 | -6.1% |
| Last Dance | 1.986 | 2.080 | 2.048 | -4.5% |
| Finishing Move | 1.020 | 1.046 | 1.038 | -2.5% |
| Standard Step | 0.993 | 0.929 | 0.929 | +6.9% |
| Technical Step | 0.552 | 0.588 | 0.585 | -6.1% |
| Tillana | 0.552 | 0.588 | 0.573 | -6.1% |
| Starfall Dance | 0.576 | 0.588 | 0.582 | -2.0% |
| Flourish | 1.058 | 1.058 | 1.053 | -0.0% |
| Devilment | 0.588 | 0.588 | 0.585 | -0.0% |
| Fan Dance | 2.575 | 2.516 | 2.660 | +2.3% |
| Fan Dance III | 2.340 | 2.328 | 2.510 | +0.5% |
| Fan Dance IV | 1.058 | 1.058 | 1.053 | -0.0% |
| all weaponskills (steps excluded) | 23.649 | 23.403 | 23.357 | +1.1% |

## 4. Burst

First six burst weaponskills after Technical Finish:

| order | parses | engine |
|---|---:|---:|
| Tillana > Dance of the Dawn > Last Dance > Finishing Move > Saber Dance > Starfall Dance | 8% | 0% |
| Tillana > Dance of the Dawn > Last Dance > Finishing Move > Starfall Dance > Saber Dance | 6% | 0% |
| Tillana > Dance of the Dawn > Last Dance > Saber Dance > Finishing Move > Starfall Dance | 3% | 0% |
| Tillana > Dance of the Dawn > Last Dance > Finishing Move > Starfall Dance > Last Dance | 3% | 0% |
| Tillana > Dance of the Dawn > Last Dance > Saber Dance > Starfall Dance > Saber Dance | 0% | 16% |
| Dance of the Dawn > Finishing Move > Last Dance > Saber Dance > Saber Dance > Tillana | 0% | 11% |

- Devilment lands a median +0.68 s from Technical Finish in the parses; the engine weaves it directly behind the finish.
- The last Standard Finish lands a median 9.1 s before Technical Step in the parses.
- Potions per parse: 1.93.

## 5. Opener

- most common in the top 10 (2 of 10): Double Standard Finish, Technical Step, Quadruple Technical Finish, Devilment, Tillana, Flourish, Shield Samba, Dance of the Dawn, Fan Dance IV, Fan Dance III, Last Dance, Finishing Move
- engine (seed 1): Double Standard Finish, Technical Step, Quadruple Technical Finish, Devilment, Tillana, Flourish, Fan Dance III, Dance of the Dawn, Fan Dance IV, Last Dance, Saber Dance, Starfall Dance

## 6. What the engine throws away (per fight, top-10 lengths)

- esprit_wasted: 39.25
- feathers_wasted: 0.23
- gcd_idle_s: 0.00
- wrong_steps: 0.00
- broken_combos: 0.00
- lapsed / overwritten procs: lapsed_SilkenSymmetry 0.25
