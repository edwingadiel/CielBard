# Ciel Bard for MMOMinion

Ciel Bard is an experimental level-100 Bard rotation addon built from the top-40 Vamp Fatale FFLogs analysis. It executes a priority system rather than replaying a fixed sequence.

Version 0.2.0 is a training-dummy MVP. Execution starts disabled and must be explicitly armed in the window.

## What it implements

- Empirical song allocation: approximately 43.8s Wanderer's Minuet, 42.3s Mage's Ballad, and 34.9s Army's Paeon.
- Strict GCD-first scheduling.
- Two-minute Raging Strikes / Battle Voice / Radiant Finale coordination.
- Proc-aware Refulgent, Blast, Resonant, and Radiant Encore consumption.
- Soul Voice pooling for burst with off-cycle Apex/Blast protection.
- Two-Empyreal-Arrow burst intent without sacrificing obvious total uses.
- DoT maintenance and optional late-buff Iron Jaws snapshots.
- Heartbreak Shot → Rain of Death replacement when cleave is profitable.
- Rolling HP-slope time-to-kill estimation and `<20s`, `20–30s`, and longer-fight behavior.
- An in-game diagnostic/configuration window.

## Installation

1. Copy the complete `CielBard` folder into the MMOMinion `LuaMods` directory for your FFXIV bot installation. The resulting folder must contain `module.def` directly.
2. Reload Lua modules or restart MMOMinion.
3. Change to Bard and open **Ciel Bard**.
4. Before enabling execution, expand **Gauge diagnostics** on a training dummy:
   - Confirm which `Player.gauge` entry rises from 0 to 100 as Soul Voice.
   - Confirm which entry reads 0–3 as Wanderer's Repertoire stacks.
   - Adjust the two index settings if the defaults differ on your client.
5. Target a training dummy, enter combat, and enable **Execute rotation**.

Execution is disabled by default.

## First test checklist

- Both DoTs are established before the opener burst.
- The addon starts Wanderer's, then changes to Mage's and Army's at the configured thresholds.
- No GCD pauses occur while the target is valid and in range.
- Refulgent is consumed before Barrage when already available.
- Apex is not held so long that it overcaps Soul Voice.
- Rain of Death replaces Heartbreak only when the configured nearby-target count is met.
- The TTK estimate stabilizes after several seconds of continuous boss damage.
- **Kill-time policy** changes from `LEARNING` to `TERMINAL`, `IDEAL_FINISH`, `EXTENDED_TAIL`, or `SUSTAIN` only after the configured confidence threshold is reached.
- The addon stops safely when disabled, out of combat, on another job, without a target, or out of range.

## Known limitations

- MMOMinion's public documentation does not define the modern Bard gauge array. Gauge indexes are therefore configurable and visibly inspectable.
- The TTK estimator is deliberately conservative and can be distorted by phase transitions, invulnerability, shields, or add targeting. Use manual TTK when testing encounter-specific endings.
- Automatic potion use is not included in v0.1 because inventory HQ/NQ item resolution should be validated on the live client first.
- This version has passed offline Lua parsing and MMOMinion API/reference checks, but has not yet been validated inside a live MMOMinion client. Treat it as a testable MVP, begin on a training dummy, and keep execution disabled until gauge diagnostics and song detection are correct.
- Third-party automation may violate game rules or account terms. Use at your own risk.

## Sources

- MMOMinion Lua API: https://wiki.mmominion.com/doku.php?id=lua_api
- MMOMinion GUI API: https://wiki.mmominion.com/doku.php?id=gui_api
- MinionLib: https://wiki.mmominion.com/doku.php?id=minionlib
- FFXIVMinion reference module: https://github.com/MINIONBOTS/FFXIVMinion
