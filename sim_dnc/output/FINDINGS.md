# CielDancer 0.1.0 — simulator findings

Measured with `sim_dnc` against the shipped engine, 2026-09-19. Sweeps: the engine pulls with a pre-pull, three potions, one 10% party-buff window of 20 s every 120 s from 0:06, the target dying at the end, every point averaged over fight lengths of 400, 460, 505 and 540 s and seeds 1-12 (48 paired fights per point). Dancer is random, so each row is a paired difference against the first row with its standard error; **a difference under about twice its standard error is noise**. With 48 pairs the noise floor is roughly 0.3-0.5%, which is coarser than the Machinist sweeps: only large effects can be resolved.

The parse comparison is in `calibration.md`.

## 1. Calibration against the top 40 Dancer parses (Vamp Fatale)

- **Ally Esprit chance fitted at 0.212.** The game only says the chance that an ally's weaponskill feeds the dancer 10 Esprit "differs according to job"; the community's estimate is about 0.20. Fitting it so the simulated Saber Dance + Dance of the Dawn rate matches the top 10 (4.17 per minute) lands on the same number, which is good evidence that the Esprit model is right.
- **Damage scalar 117.8**, mean residual 0.88% (worst 3.9%); on that scale the engine simulates 1.4% below the top-10 mean. Auto attacks are 10% of a Dancer's damage and are not modelled.
- **Cast rates against the top 10:** all weaponskills +1.0%, Finishing Move 0.0%, Flourish, Devilment and Fan Dance IV 0.0%, Technical Step -2.0% (the shortest kills still end before a fifth one pays), Saber Dance +3.3%. No proc lapsed or was overwritten in any re-simulated parse.
- **Opener:** the engine's matches the most common top-10 opener up to the first Finishing Move: Standard Finish as the pull, Technical Step, Quadruple Technical Finish, Devilment, Tillana, Flourish, Dance of the Dawn, Fan Dance III / IV, Last Dance. It differs after that because the engine's pre-pull dance happens right before the pull, not at -15 s, so Standard Step's shared recast brings Finishing Move back about ten seconds later than in a countdown pull. Arming the pre-pull fifteen seconds early reproduces the players' timing.
- **Burst order:** the parses' dominant order is Tillana, Dance of the Dawn, Last Dance, Finishing Move, Saber Dance, Starfall Dance, with the last three permuted freely. The engine's list is that order.
- Devilment lands a median 0.68 s after Technical Finish in the parses; the engine weaves it directly behind the finish.

## 2. Sweeps

| setting | values: paired difference vs first row (standard error) | verdict |
|---|---|---|
| `featherOffcycleCount` | 1: 0 · 3: +0.40% (0.29) · **4: +0.90% (0.32)** | pooling feathers for the burst is the one clearly resolved gain: **+0.9%** |
| `technicalMinimumTTK` | 8: 0 · **12: 0.00%** · 20: -0.16% (0.05) | a last Technical Step pays for itself with as little as 12 s left; **changed from 20 to 12** |
| `burstSaberOvercapEsprit` | 60: 0 · 70: +0.43% (0.15) · **80: +0.46% (0.15)** · off: +0.47% (0.14) | spending too eagerly inside the burst costs 0.45%; 70, 80 and off are the same, and 80 wastes 25% less Esprit than off |
| `tillanaMaxEsprit` | 0: 0 · **30: +0.14% (0.24)** · 50: -0.19% (0.40) | not resolved; The Balance's 30 kept |
| `saberOffcycleEsprit` | 50: 0 · 70: -0.03% (0.35) · **80: -0.30% (0.43)** · 90: -0.48% (0.54) | not resolved. The trend favours spending Esprit earlier, but it is inside the noise; The Balance's 80 kept. Worth a larger run. |
| `standardBeforeTechnicalSeconds` | **5: 0** · 9: -0.15% (0.27) · 13: +0.04% (0.27) · 16: -0.07% (0.26) | no effect; The Balance's rule kept |
| `lastDanceBurstLeadSeconds` | 0: 0 · **15: +0.02% (0.06)** · 30: +0.19% (0.28) | no effect on damage. 15 is what stops a kept Last Dance from lapsing mid-dance (section 3). |

## 3. What the offline client caught

- **A kept Last Dance lapsed.** The first rule kept it for the burst whenever it would still be up when Technical Step came off cooldown. It then sat through the seven-second dance, Tillana and Dance of the Dawn, and ran out. It now has to outlast the wait plus fifteen seconds, and a Last Dance or a proc that is about to lapse is pressed first even inside the burst.
- **Bladeshower without Windmill.** The AoE filler pressed Bladeshower on every GCD because it is always "ready"; it is only a combo finisher. The engine now tracks which of the two combos is open.
- **Technical-first opener.** Without a pre-pull the engine opened with Technical Step and ran the whole burst without its own Standard Finish buff. Standard Step now goes first when the buff is missing.

## 4. Shape of a six-minute fight (8 seeds, shipped defaults)

No wrong step, no broken combo, no lapsed or overwritten proc, no idle GCD, three of every two-minute action, Devilment directly behind every Technical Finish, never more than one weave behind a finish or two behind a weaponskill, none inside a dance. About 30 Esprit and under 0.1 feathers go over the cap per eight-minute fight.

## 5. Still unverified

Everything in HANDOFF.md's Dancer list, above all the step-gauge layout. The simulator publishes the gauge in the layout the engine assumes, so it cannot find a mismatch.
