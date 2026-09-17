# Ciel Bard for MMOMinion

Ciel Bard is an experimental level-100 Bard rotation addon built from the top-40 Vamp Fatale FFLogs analysis. It executes a priority system rather than replaying a fixed sequence.

Version 0.4.0 is a training-dummy MVP. Execution starts disabled and must be explicitly armed in the window. The optimized setup remains the default; advanced customization is hidden behind one opt-in setting.

## What it implements

- Empirical song allocation: approximately 43.8s Wanderer's Minuet, 42.3s Mage's Ballad, and 34.9s Army's Paeon.
- Strict GCD-first scheduling.
- Two-minute Raging Strikes / Battle Voice / Radiant Finale coordination.
- Proc-aware Refulgent, Blast, Resonant, and Radiant Encore consumption.
- Soul Voice pooling for burst with off-cycle Apex/Blast protection.
- Two-Empyreal-Arrow burst intent without sacrificing obvious total uses.
- DoT maintenance and optional late-buff Iron Jaws snapshots.
- Heartbreak Shot → Rain of Death replacement when cleave is profitable, with separate nearby-target thresholds for Ladonsbite, Shadowbite, and Rain of Death.
- Multi-dotting: Stormbite and Caustic Bite are kept on up to three additional engaged enemies that are healthy enough to pay back the GCD, without changing your current target. One checkbox turns it off.
- Coda-aware Radiant Finale: never requested at zero codas, and a song that is due within two seconds is allowed to land first when it would add a coda.
- Configurable DoT gate for the two-minute burst (none, at least one DoT, or both). The default starts Raging Strikes after the first DoT, matching the standard opener.
- Opt-in Gemdraught of Dexterity use, weaved immediately before Raging Strikes so the 30-second effect covers the whole buff package. HQ is preferred, the newest grade in your bags wins, and a potion on cooldown never delays the burst.
- Rolling HP-slope time-to-kill estimation and `<20s`, `20–30s`, and longer-fight behavior.
- Optional per-ability Auto/Off controls backed by a centralized capability layer.
- Presets for optimized, conservative, no-party-buff, no-DoT, single-target, and GCD-only play.
- Smart continuation when abilities are disabled, including manual DoT refreshes, legal reduced-song cycles, and a permanent Burst Shot → Heavy Shot fallback.
- Opt-in Second Wind, Nature's Minne, Troubadour, and Warden's Paean rules.
- An in-game diagnostic/configuration window.

## Normal and advanced use

Most users can leave **Advanced customization → Enable custom settings** off. In that state CielBard always uses the optimized action set, regardless of any old custom values saved in settings.

Advanced mode exposes presets, Full/GCD-only/oGCD-only execution, pooling and terminal-dump policies, and Auto/Off controls for songs, DoTs, burst buffs, proc/gauge actions, damage oGCDs, AoE actions, and utility. Manual edits select the `Custom` preset. Invalid or ineffective combinations produce visible warnings and the priority engine continues with the best legal enabled action.

The non-configurable emergency GCD chain is:

1. Enabled proc or gauge GCD.
2. Enabled DoT action when worthwhile.
3. Burst Shot.
4. Heavy Shot for level sync.

Disabling Apex removes Apex pooling, disabling Iron Jaws switches enabled DoTs to individual refreshes, disabling party buffs removes holds that exist only for those buffs, and disabling songs constructs a cycle from whatever songs remain.

## Installation

1. Copy the complete `CielBard` folder into the MMOMinion `LuaMods` directory for your FFXIV bot installation. The resulting folder must contain `module.def` directly.
2. To run it as an ACR profile, also copy `CielBard/acr/CielBard.lua` to `LuaMods/ACR/CombatRoutines/CielBard.lua`. "CielBard" then appears in the ACR PVE Profile dropdown, and the ACR **Enabled** toggle starts and stops the rotation. **Profile Options** opens the Ciel Bard window. Without the stub, CielBard runs standalone from its own window.
3. Reload Lua modules or restart MMOMinion.
4. Change to Bard and open **Ciel Bard** (or select the CielBard ACR profile).
5. Before enabling execution, expand **Gauge diagnostics** on a training dummy:
   - Confirm which `Player.gauge` entry rises from 0 to 100 as Soul Voice.
   - Confirm which entry reads 0–3 as Wanderer's Repertoire stacks.
   - Adjust the two index settings if the defaults differ on your client.
6. Target a training dummy, enter combat, and enable **Execute rotation** (standalone) or the ACR **Enabled** toggle (ACR mode).

Execution is disabled by default.

## Optional: reduce animation lock for better weaving

CielBard works on its own. For even better results, run an animation-lock compensation tool alongside it. These tools remove your ping from the client's animation lock, so double weaves fit cleanly inside the GCD even at 80–150 ms latency:

- [XivAlexander](https://github.com/Soreepeong/XivAlexander): standalone, no Dalamud needed. The simplest choice next to MMOMinion.
- [NoClippy](https://github.com/UnknownX7/NoClippy): a Dalamud plugin that does the same thing without ping or opcodes. Only for setups that already run Dalamud.

Run only one of them. Both are designed to simulate low ping without sending actions earlier than the real server lock allows. CielBard's request throttle and pulse rate (60 ms and 30 ms by default) are low enough to take advantage of the shorter lock automatically. Measured on a striking dummy, oGCD-to-oGCD gaps drop by roughly your round-trip time.

## First test checklist

- Stormbite lands, Wanderer's starts, and Raging Strikes follows the first DoT (the default **At least one** gate).
- The addon starts Wanderer's, then changes to Mage's and Army's at the configured thresholds, and the **codas** counter in the window rises with each song and returns to zero on Radiant Finale.
- Radiant Finale fires at one coda in the opener and at three codas in later windows.
- With **Use Gemdraught of Dexterity** on, the window shows the potion it found and the potion is used in the weave before Raging Strikes.
- With **Multi-dot nearby enemies** on and a second engaged dummy in range, both DoTs are applied to it while your target stays unchanged.
- No GCD pauses occur while the target is valid and in range.
- Refulgent is consumed before Barrage when already available.
- Disabling an action under **Advanced customization** causes the engine to skip it without pausing the GCD.
- The preset buttons restore a complete, deterministic configuration before applying their overrides.
- Apex is not held so long that it overcaps Soul Voice.
- Rain of Death, Ladonsbite, and Shadowbite each replace their single-target action only when their own nearby-target count is met.
- The TTK estimate stabilizes after several seconds of continuous boss damage.
- **Kill-time policy** changes from `LEARNING` to `TERMINAL`, `IDEAL_FINISH`, `EXTENDED_TAIL`, or `SUSTAIN` only after the configured confidence threshold is reached.
- The addon stops safely when disabled, out of combat, on another job, without a target, or out of range.

## Known limitations

- MMOMinion's public documentation does not define the modern Bard gauge array. Gauge indexes are therefore configurable and visibly inspectable.
- The TTK estimator is deliberately conservative and can be distorted by phase transitions, invulnerability, shields, or add targeting. Use manual TTK when testing encounter-specific endings.
- Potion use is opt-in. It relies on FFXIVMinion's `GetItem` helper (falling back to a scan of the four inventory bags) and the item's `IsReady`/`Cast` methods; validate on a training dummy that the potion is consumed once and that the weave count stays correct.
- Multi-dot only considers enemies that MMOMinion reports as in combat. Whether `entity.incombat` and the `incombat` EntityList filter behave as expected in every duty must be confirmed live. Codas are tracked locally from observed song casts rather than read from the gauge.
- Utility automation is opt-in. Warden's Paean debuff detection and the defensive HP thresholds require live-client validation before duty use.
- This version has passed offline Lua parsing and MMOMinion API/reference checks, but has not yet been validated inside a live MMOMinion client. Treat it as a testable MVP, begin on a training dummy, and keep execution disabled until gauge diagnostics and song detection are correct.
- Third-party automation may violate game rules or account terms. Use at your own risk.

## Sources

- MMOMinion Lua API: https://wiki.mmominion.com/doku.php?id=lua_api
- MMOMinion GUI API: https://wiki.mmominion.com/doku.php?id=gui_api
- MinionLib: https://wiki.mmominion.com/doku.php?id=minionlib
- FFXIVMinion reference module: https://github.com/MINIONBOTS/FFXIVMinion

## Offline tests

From the repository root:

```bash
python -m pip install -r tests/requirements.txt
python tests/run_mock_tests.py
```

The suite parses every Lua source file and checks advanced-mode invariants including Apex Off, all songs Off, Iron Jaws Off, no DoTs, Heavy Shot fallback, and GCD-only execution. It also covers per-action AoE thresholds, the burst DoT gate, coda tracking and Radiant Finale holds, potion weaving and its off/cooldown/missing cases, and multi-dot target selection.
