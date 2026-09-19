# sim_dnc — Dancer simulator

A level-100 Dancer simulator that **drives the shipped CielDancer Lua engine** rather than re-implementing it. `CielDancer_Data.lua` and `CielDancer_Rotation.lua` are loaded verbatim; nothing under `CielDancer/` is modified by a run. It follows `sim_mch/` piece for piece and reuses its small shared helpers.

| Piece | Role |
|---|---|
| `data/*.json` | Every id, potency, recast, proc chance, Esprit and feather amount, buff size and stat. Ids are checked against the shipped Lua by `tests/test_dnc_sim.py`. |
| `fakeclient.lua` | The imitation MMOMinion client: the GCD with its 1.0 s step and 1.5 s finish variants, animation lock, **random step sequences published through the gauge** (slots 1-7, the layout the engine reads), the shared Standard Step / Finishing Move recast, 50% procs, Fourfold Feathers, Esprit from the dancer, the partner and the party, every Ready status, the combo and its cross-breaks, the potion, clustered extra targets, a linear kill time. It logs every cast with the buffs that were up, and counts what was thrown away: Esprit and feathers over the cap, procs that lapsed or were overwritten, wrong steps, idle time. |
| `core.py` | Builds the runtime, applies engine overrides, runs the fight, prices the log: combo potency, AoE falloff, Standard and Technical Finish (multiplicative), Devilment's crit and direct-hit rates, Starfall Dance as a guaranteed critical direct hit, the potion, optional party-buff windows. |
| `run.py`, `sweep.py`, `calibrate.py` | Command line. |

**Dancer is random**, unlike Machinist: a fight is a function of (configuration, seed). `sweep` therefore runs every point on the same seeds and reports the paired difference against the first row with its standard error (`sem_pct`); a difference smaller than about twice its `sem_pct` is noise.

```bash
python -m sim_dnc.run --seconds 360 --seed 3 --timeline 30
python -m sim_dnc.run --seconds 60 --self-pull --potions 1 --timeline 25     # pre-pull and opener
python -m sim_dnc.run --seconds 360 --no-party --seeds 20                    # solo striking dummy
python -m sim_dnc.sweep --seeds 1-24 --self-pull --potions 3 --party-buffs 1.10 --kill-at-end \
  --over seconds=400,460,505,540 --axis "technicalMinimumTTK=8,12,20"
python -m sim_dnc.calibrate --out sim_dnc/output/calibration.md --write       # needs dnc-analysis/output/summary.json
```

## Limits

- **Esprit from allies is one fitted number.** The game only says an ally's chance to feed Esprit "differs according to job". `calibrate` fits a single chance (0.205; the community's estimate is about 0.20) so the simulated Saber Dance rate matches the top parses, with every ally pressing one GCD every 2.5 s.
- `potency_to_damage` is one fitted scalar; it absorbs gear, party buffs received and real downtime. Judge a rotation from cast rates, not from DPS. Auto attacks (10% of a Dancer's damage) are not modelled.
- The partner's share of Standard Finish and Devilment is not counted: it is the same whatever the engine does.
- No movement or downtime, no En Avant or Improvisation, and extra targets all stand inside the five-yalm circle and never die.
- The client answers the way the engine *assumes* the live client does. It cannot discover an API mismatch; only a live session can.
