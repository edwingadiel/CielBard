# sim_mch — Machinist simulator

A level-100 Machinist simulator that **drives the shipped CielMachinist Lua engine** rather than re-implementing it. `CielMachinist_Data.lua` and `CielMachinist_Rotation.lua` are loaded verbatim; nothing under `CielMachinist/` is modified by a run.

It is a separate package from `sim/` on purpose. The Bard simulator's core is built around songs, Repertoire and DoTs and its tests pin the Bard engine by hash; Machinist shares none of those rules.

## How it works

| Piece | Role |
|---|---|
| `data/actions.json`, `statuses.json`, `job.json`, `stats.json` | Every id, potency, recast, charge count, gauge amount, Queen coefficient and stat. No mechanic constant lives in code. Ids are checked against the shipped Lua by `tests/test_mch_sim.py`. |
| `fakeclient.lua` | The imitation MMOMinion client, in Lua so the engine runs at full speed: GCD and the 1.5 s Overheated GCD, animation lock (+ ping, + seeded jitter), charged cooldowns with the `cd` / `cdmax = recast x charges` layout, Heat, Battery, statuses, combo state (`lastcomboid`, `combotimeremain`), Wildfire hit counting, the Queen lockout, the potion through `GetItem`, clustered extra targets, a linear kill time. It produces a cast log and idle / cap / waste counters. |
| `core.py` | Builds the runtime, applies engine overrides, runs the fight, then prices the log: combo and Overheated potency, AoE falloff, Reassemble and Full Metal Field as guaranteed critical direct hits, Wildfire (no crit, buffs snapshotted on application), Bioblaster ticks, the Queen's hits scaled by battery, the potion and optional party-buff windows. |
| `run.py`, `sweep.py` | Command line. |

**Machinist has no random procs**, so the rotation is a pure function of the configuration. The simulator therefore reports *expected* DPS (crit and direct hit at their mean): one fight per configuration, and differences between two configurations are exact rather than statistical. `--rolled N` draws real crit/direct-hit rolls if a distribution is wanted. A 360 s fight takes about half a second.

## Running it

```bash
# one fight, with the first 30 s of the timeline
python -m sim_mch.run --seconds 360 --party-buffs 1.10 --timeline 30

# the engine pulls: pre-pull Reassemble and potion, then the opener
python -m sim_mch.run --seconds 60 --self-pull --potions 2 --timeline 15

# a real kill, so the engine's TTK bands and terminal dump are exercised
python -m sim_mch.run --seconds 600 --kill-time 420

# sweep a setting, averaged over several fight lengths, target dying at the end
python -m sim_mch.sweep --party-buffs 1.10 --kill-at-end \
  --over seconds=300,360,420,480,540 --axis "queenBatteryOffcycle=50,70,90"

# engine settings use dotted keys
python -m sim_mch.run --set advancedEnabled=true --set abilities.Wildfire=false
```

Always sweep with `--over seconds=...`: a single fight length decides a comparison by whichever Hypercharge or Queen happens to fall just inside the end of the fight.

`--party-buffs MULT` adds one 20 s window every 120 s from 0:06. The engine cannot see party buffs, so they change the price of a rotation and never the rotation itself.

## Limits

- **Uncalibrated.** `potency_to_damage` is 100 and the stat profile is the Bard simulator's. There is no Machinist parse study, so DPS figures are comparable with each other and with nothing else.
- **The Queen's timeline is assumed.** Her total (26.6 potency per battery, The Balance) and per-hit coefficients (job guide) are sourced; when each hit lands after the summon is not. Her 0.89 potency scale is The Balance's normalized-pet figure.
- **No auto attacks**, no movement or downtime, no Flamethrower, and extra targets all stand in the cluster and never die.
- The client answers the way the engine *assumes* the live client does (see "Unverified on a live client" in `HANDOFF.md`). It cannot discover an API mismatch; only a live session can.

Results so far are in `output/FINDINGS.md`.
