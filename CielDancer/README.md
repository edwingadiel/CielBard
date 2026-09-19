# CielDancer

Experimental level-100 Dancer rotation module for FFXIVMinion/MMOMinion, built on the same engine design as CielBard and CielMachinist: a GCD-first priority engine with a central Auto/Off capability layer, kill-time awareness, a pending-request guard, and an ACR profile.

Version 0.1.0 is **offline-tested only**. It has not been run in a live client yet. Execution is disabled by default.

## Install

1. Copy `CielDancer.lua`, `CielDancer_Data.lua`, `CielDancer_Rotation.lua` and `module.def` into `LuaMods/CielDancer/`.
2. To run it through ACR, copy `CielDancer/acr/CielDancer.lua` to `LuaMods/ACR/CombatRoutines/CielDancer.lua` and pick **CielDancer** in ACR's Dancer dropdown. ACR's Enabled toggle is then the master switch.
3. Reload Lua modules or restart MMOMinion, switch to Dancer, and open the **Ciel Dancer** window.

It installs next to CielBard and CielMachinist; the three share no globals or settings. **Closed Position is left to you**: pick your dance partner by hand (the window warns when you are in a party without one).

## What it does

Priorities follow The Balance's level-100 guide, the official job guide (Patch 7.5 potencies), and what the top 40 Vamp Fatale parses actually press (`sim_dnc/output/calibration.md`).

**Dancing.** While a dance is up nothing but its steps and its finish is pressed, and nothing is weaved. The step sequence is random; the engine reads it from the gauge (slots 3-6, with slot 7 counting the steps done) and falls back to the hotbar highlight. If it can read neither it waits rather than guess. The finish is a 15 yalm circle around you, so it is held for a target that is further away until the dance is about to lapse.

**Burst.** Technical Step on cooldown, Devilment weaved directly behind Technical Finish, then: a proc or Starfall Dance that is about to lapse, Saber Dance from 80 Esprit, **Tillana → Dance of the Dawn → Last Dance → Finishing Move → Saber Dance → Starfall Dance**, then procs and the combo. Tillana waits while its 50 Esprit would overcap. Flourish, Fan Dance III / IV and every feather are weaved inside the window.

**Outside the burst** (The Balance's list): lapsing procs, Saber Dance from 85 Esprit, Finishing Move / Standard Step on cooldown (an unused Last Dance is pressed first so the dance cannot overwrite it), Saber Dance from 80, Last Dance, Fountainfall, Reverse Cascade, Fountain, Cascade. Esprit and feathers are pooled for the burst: feathers are only spent at four, and a Last Dance or Fan Dance IV is kept when the burst will arrive while it is still up.

- Without a pre-pull the Standard Finish buff is missing, so **Standard Step goes before Technical Step** at the start of a fight.
- One weave behind a finish or a Step press (1.5 s), two behind a 2.5 s weaponskill, none inside a dance.
- AoE replacements (Windmill, Bladeshower, Rising Windmill, Bloodshower, Fan Dance II) from two targets, counted inside the five-yalm circle around **you**, not the target.
- **Pre-pull.** With *Require combat* off the engine pulls: Standard Step, both steps, the potion, then Standard Finish as the pull. With *Require combat* on, press **Pre-pull now** about fifteen seconds before the pull: it dances both steps and holds the finish until combat starts. It never pulls for you, and the dance lapses after fifteen seconds.

Not implemented: Closed Position / partner choice, En Avant, Improvisation, Head Graze, encounter-specific logic.

## First live test

Leave execution off and check these on a striking dummy. They are assumptions about the MMOMinion API that the offline tests cannot prove:

1. **Gauge diagnostics.** Defaults come from the Dancer profile bundled with FFXIVMinion (`MadaoFiles/CombatProfiles/Dancer`): slot 1 feathers, slot 2 Esprit, slots 3-6 the step sequence (1 Emboite, 2 Entrechat, 3 Jete, 4 Pirouette), slot 7 steps done. **Press Standard Step by hand once** with the diagnostics open: two step slots should fill, "next step" should name the step the game highlights, and slot 7 should count up as you press them.
2. Esprit should climb by 5 / 10 per weaponskill once Standard Finish is up; feathers by one on a lucky Reverse Cascade / Fountainfall.
3. Enable execution and watch a full dance: every step right first time, the finish immediately after the last step, Devilment right behind Technical Finish, no repeated failed requests in the console. `debug` prints the gauge once per second.

A solo dummy generates far less Esprit than a party (no partner, no party procs), so expect few Saber Dances there.

## Offline tests

```bash
python tests/run_dnc_mock_tests.py -v
python tests/run_dnc_gui_tests.py
python -m unittest tests.test_dnc_sim
```

## Simulator

```bash
python -m sim_dnc.run --seconds 360 --seed 3 --timeline 30 --self-pull --potions 2
python -m sim_dnc.sweep --seeds 1-24 --kill-at-end --over seconds=400,505 --axis "saberOffcycleEsprit=70,80,90"
```

See `sim_dnc/README.md` and `sim_dnc/output/FINDINGS.md`.

## Disclaimer

Third-party automation may violate game rules or account terms. Use at your own risk.
