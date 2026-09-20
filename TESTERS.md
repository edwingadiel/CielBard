# Testing the Ciel modules

Three experimental level-100 rotation modules for FFXIVMinion / MMOMinion: **CielBard 0.5.2**, **CielMachinist 0.2.1** and **CielDancer 0.1.0**. All three have been run on a live training dummy by the maintainer. **None has been tested in a duty yet.** That is what you are helping with.

Third-party automation may violate the game's terms of service. Use at your own risk.

## Install

The release zip mirrors the `LuaMods` folder. Unzip it **into your MMOMinion `LuaMods` folder** (for example `...\Bots\FFXIVMinion64\LuaMods`) so that you end up with:

```
LuaMods\CielBard\        (3 .lua files + module.def)
LuaMods\CielMachinistLuaMods\CielDancerLuaMods\ACR\CombatRoutines\CielBard.lua
LuaMods\ACR\CombatRoutines\CielMachinist.lua
LuaMods\ACR\CombatRoutines\CielDancer.lua
```

You can install just one job: take its folder and its one file under `ACR\CombatRoutines`. The modules share nothing, and each one only ever acts on its own job.

Then restart MMOMinion (or reload Lua modules), switch to the job, and pick the matching **Ciel...** profile in ACR's dropdown. ACR remembers it per job. ACR's **Enabled** toggle is the on/off switch; nothing runs until you turn it on.

Installing from the repository instead: copy the three `.lua` files and `module.def` from the module's folder, and `acr/<Module>.lua` into `LuaMods\ACR\CombatRoutines\`.

## First run, on a striking dummy

1. Leave ACR disabled and open the module's window (**Ciel Bard / Ciel Machinist / Ciel Dancer**). Open **Gauge diagnostics**.
   - Bard: Soul Voice should read 0-100 and Repertoire 0-3.
   - Machinist: Heat climbs 5 per combo weaponskill, Battery 10 on Heated Clean Shot; Drill shows `n/2` charges.
   - Dancer: press Standard Step by hand once. Two step slots fill and "next step" names the step the game highlights.
   If a value looks wrong, move the index slider next to it until it matches.
2. Enable ACR and watch one opener and one two-minute burst.
3. Dancer: choose your dance partner yourself (Closed Position is not automated). On a solo dummy there is little Esprit, so few Saber Dances is normal.

Optional but recommended: [XivAlexander](https://github.com/Soreepeong/XivAlexander) or [NoClippy](https://github.com/UnknownX7/NoClippy) for cleaner double weaves. Run only one of them.

## Safe defaults

- Execution is off until you enable it. Potions are **off** (they consume inventory); turn "Use Gemdraught of Dexterity" on if you want them.
- Utility actions (Second Wind, Troubadour, Tactician, Shield Samba, Curing Waltz ...) are off unless you enable them under *Advanced customization*.
- The modules never change your target and never move your character.
- "Require combat" is on: the module waits for the pull. The **Pre-pull now** button (Machinist, Dancer) prepares the opener without pulling for you.

## What to report

Please open an issue at <https://github.com/edwingadiel/CielBard/issues> (or message the maintainer) with:

- job, module version (shown in the MMOMinion console at load: `[CielDancer] Loaded v0.1.0`), and what content you were in;
- what happened and what you expected: a stall, a wrong button, clipping, a cooldown drifting, the rotation stopping after a mechanic or a death;
- the **Current decision** line from the window at that moment, and any red Lua error from the console;
- if you can, turn on `debug` for a minute: it prints one line per second with the gauge and timing values the engine sees.

Things most worth checking in real content: behaviour after deaths and raises, target swaps and untargetable phases, multi-target pulls (AoE thresholds), level-synced duties, the kill-time estimate near the end of a fight (the window shows it), and high-latency play.
