# CielMachinist

Experimental level-100 Machinist rotation module for FFXIVMinion/MMOMinion, built on the same engine design as CielBard: a GCD-first priority engine with a central Auto/Off capability layer, kill-time awareness, a pending-request guard, and an ACR profile.

Version 0.2.1 has been run on a live training dummy (2026-09-19) and behaved correctly; it has not been validated in duties. Execution is disabled by default.

## Install

1. Copy the whole `CielMachinist` folder into your MMOMinion `LuaMods` directory. `module.def` must sit directly inside `LuaMods/CielMachinist`.
2. To run it through ACR, copy `CielMachinist/acr/CielMachinist.lua` to `LuaMods/ACR/CombatRoutines/CielMachinist.lua` and pick **CielMachinist** in ACR's Machinist dropdown. ACR's Enabled toggle is then the master switch. Without that file the module runs standalone from its own window.
3. Reload Lua modules or restart MMOMinion, switch to Machinist, and open the **Ciel Machinist** window.

CielMachinist and CielBard can be installed side by side; they share no globals or settings.

## What it does

Priorities follow The Balance's level-100 guide and the official job guide (Patch 7.5 potencies).

**GCD**, in order:

1. Blazing Shot while Overheated (Auto Crossbow at 6+ clustered targets).
2. Air Anchor, a Drill stack that is capped, Chain Saw, Excavator, Drill (Bioblaster takes the Drill slot at 3+ targets while its DoT is down).
3. Full Metal Field.
4. Scattergun at 3+ targets, otherwise the Heated Split → Slug → Clean combo. Split Shot is the permanent, non-configurable filler.

The GCD is held for up to 0.4 s when Air Anchor or Chain Saw is about to come back, instead of pressing a filler that would drift the tool by a whole GCD.

**oGCD**, in order: opt-in utility, Barrel Stabilizer on cooldown (with the opt-in potion just before it), Wildfire, Hypercharge, Reassemble, Automaton Queen, Double Check / Checkmate.

- **Hypercharge** is refused while Air Anchor or Chain Saw would come off cooldown within 8 s, while a Drill stack would cap, or while Excavator or Full Metal Field is waiting to be pressed. It is kept for a Wildfire that is less than 12 s away, and never allowed to let the Hypercharged buff expire.
- **Wildfire** goes out in the weave slot right behind Hypercharge, so five Blazing Shots plus the next weaponskill make six hits with more than a second to spare. This is the placement The Balance calls the most ping-friendly. *Rotation tuning* also offers "One weaponskill before" Hypercharge, late-weaved, which is what most top parses do; the simulator prices the two identically with clean timing and finds the default more robust to latency.
- **Pre-pull.** With *Require combat* off the engine pulls, so it presses Reassemble (and the potion, if potion use is on) immediately before its first weaponskill. With *Require combat* on, target the enemy and press **Pre-pull now** about five seconds before the pull: the engine presses Reassemble and the potion and then waits; it never pulls for you. Reassemble is only taken from a full stack, so an aborted pull costs nothing but the recharge.
- **Reassemble** is only spent when Drill, Air Anchor, Chain Saw or Excavator is certain to be the next weaponskill. It is never put on Full Metal Field, Blazing Shot, Bioblaster or a filler. One charge is kept for the burst.
- **Automaton Queen** is summoned near the battery cap off-cycle, takes a "last call" just before the pre-burst refill window, and inside the burst waits for Air Anchor / Chain Saw / Excavator to top her off (the even-minute Queen goes out at 90–100).
- **Double Check / Checkmate** are spent on cooldown from whichever stack is fuller, pooled for 15 s before the burst unless a stack would cap, and single-weaved after every Blazing Shot.
- One weave after a 1.5 s weaponskill, two after a 2.5 s one.

- **Heat pooling** for a second, heat-funded Hypercharge inside the two-minute burst is available under *Rotation tuning* ("Heat kept for a second burst Hypercharge", try 45) and ships **off**: the simulator measures it as a small loss on average. See `sim_mch/output/FINDINGS.md`.

Not implemented: Flamethrower, Dismantle, Head Graze, and encounter-specific logic.

## First live test

Leave execution off and check these on a striking dummy first. They are assumptions about the MMOMinion API that the offline tests cannot prove:

1. **Gauge diagnostics → Heat / Battery indexes.** Defaults are slot 1 (Heat) and slot 2 (Battery), taken from FFXIVMinion's bundled Machinist profile. Heat climbs 5 per combo weaponskill; Battery climbs 10 on Heated Clean Shot.
2. **Combo line in Gauge diagnostics.** `lastcomboid` should show the last combo weaponskill and "next step" should cycle 1 → 2 → 3.
3. Turn on `debug` (saved setting) or watch the window: Drill should show `n/2` charges and Double Check / Checkmate `n/3`. If they show `?`, the client is not reporting charged cooldowns the way the engine expects.
4. Enable execution. Watch for: no GCD gaps, five Blazing Shots in every Hypercharge with exactly one weave after each, Wildfire directly after Hypercharge, Reassemble only ahead of a tool, and no repeated failed requests in the console.

Then work through the advanced toggles, AoE thresholds on a pack of dummies, and the kill-time bands.

Weaving improves with [XivAlexander](https://github.com/Soreepeong/XivAlexander) or [NoClippy](https://github.com/UnknownX7/NoClippy), and Machinist gains more than most jobs because of the single weave inside every 1.5 s Overheated weaponskill.

## Offline tests

```bash
python tests/run_mch_mock_tests.py -v
python tests/run_mch_gui_tests.py
python -m unittest tests.test_mch_sim
```

`run_mch_mock_tests.py` parses every Lua file, runs direct priority cases against a static mocked runtime, and then drives the shipped engine through `sim_mch`'s time-stepped fake client (GCD, animation lock, charges, Heat, Battery, statuses, Wildfire hit counting) for the opener, the pre-pull and a six-minute dummy fight. `-v` prints the opener timeline and the fight statistics.

## Simulator

`sim_mch/` prices the engine's rotation and sweeps its settings:

```bash
python -m sim_mch.run --seconds 360 --party-buffs 1.10 --timeline 30
python -m sim_mch.sweep --party-buffs 1.10 --kill-at-end --over seconds=300,360,420,480,540 --axis "queenBatteryOffcycle=50,70,90"
```

See `sim_mch/README.md` and `sim_mch/output/FINDINGS.md`. Every shipped default is the best value the sweeps found.

## Disclaimer

Third-party automation may violate game rules or account terms. Use at your own risk.
