# CielBard Development Handoff

## Project summary

CielBard is an experimental level-100 Bard rotation module for FFXIVMinion/MMOMinion. It was designed from an event-level analysis of the top 40 Bard parses for Vamp Fatale rather than from a single copied parse. The core conclusion was that high-end Bard play is a state-driven priority problem: procs, gauge, songs, target count, cooldown availability, and expected kill time change the best next action.

The current release is **v0.5.2**. On 2026-09-19 the maintainer ran it through the ACR profile on a live training dummy and reported it working correctly; no session log was captured, so the per-item checklist under *Installation and first live test* (each advanced toggle, AoE thresholds, kill-time bands) is not individually signed off, and it has not been run in duties. Execution is disabled by default.

A second module, **CielMachinist 0.2.0**, now lives in `CielMachinist/`; see *Machinist module* at the end of this document.

v0.5.2 implements the engine half of the external v0.5.1 code review (`REVIEW_0.5.1.md`): Barrage-aware Shadowbite, multi-dot off by default, a lazy ACR stub that survives reverse load order, pending-request dedupe, a complete Optimized-preset reset, and `debug` off. See *Engine changes made from the 0.5.1 code review* below.

v0.4.0 added five behaviors on top of v0.3.0: opt-in potion use, coda-aware Radiant Finale, per-action AoE thresholds, a configurable DoT gate before the two-minute burst, and a multi-dot toggle. Each has regression cases in `tests/run_mock_tests.py`.

Repository: <https://github.com/edwingadiel/CielBard>

## Current status

Implemented:

- GCD-first Bard priority engine.
- Empirical song-cycle timing.
- Two-minute burst coordination.
- Proc, Soul Voice, DoT, AoE, and shared-charge handling.
- Confidence-gated time-to-kill estimation and terminal behavior.
- Opt-in advanced customization with per-ability Auto/Off controls.
- Presets and partial-execution modes.
- Configuration warnings and safe fallback behavior.
- Opt-in utility rules.
- Opt-in Gemdraught of Dexterity use weaved before Raging Strikes.
- Coda tracking and coda-aware Radiant Finale timing.
- Per-action AoE thresholds for Ladonsbite, Shadowbite, and Rain of Death, plus a separate Barrage-only Shadowbite threshold.
- Configurable DoT gate (NONE / ONE / BOTH) before starting the two-minute burst.
- Multi-dot maintenance on additional engaged enemies, with a toggle (off by default since 0.5.2).
- Pending-request dedupe so client latency cannot turn one decision into repeated casts.
- Lua parsing and mocked-runtime invariant tests.

Still required:

- Duty-level live validation (a training-dummy ACR session passed on 2026-09-19).
- Verification of Bard gauge-array indexes on the current client.
- Confirmation of action readiness, transformed-action, status, and debuff fields.
- Animation-lock and weave timing calibration.
- Real encounter testing and target-selection improvements.
- More complete encounter-aware TTK handling.

## Repository layout

| Path | Purpose |
|---|---|
| `CielBard/` | Installable MMOMinion module. Copy this folder into `LuaMods`. |
| `CielBard/CielBard_Data.lua` | Action/status IDs, defaults, ability capabilities, and presets. |
| `CielBard/CielBard_Rotation.lua` | Runtime state, TTK estimator, context builder, priorities, casting, and safeguards. |
| `CielBard/CielBard.lua` | Initialization, persisted settings, presets, and GUI. |
| `CielBard/module.def` | MMOMinion module manifest; currently version 0.5.2. |
| `bard-analysis/` | Sanitized FFLogs collection and analysis scripts. |
| `bard-analysis/output/merged-report.md` | Best single summary of the research and recommended policy. |
| `tests/run_mock_tests.py` | Lua parser and mocked-MMOMinion invariant suite. |
| `tests/requirements.txt` | Offline test dependencies. |

Raw FFLogs events, credentials, local reference checkouts, screenshots, generated archives, and error dumps are intentionally excluded from version control.

## Research basis

The dataset contains the top 40 Bard aDPS rankings collected for Vamp Fatale, encounter 101 in zone 73. Complete source-filtered cast and damage timelines were analyzed. The top 10 were compared with ranks 21–40, while ranks 11–20 remained in population-level statistics.

The strongest observations were:

1. Top players gained approximately **0.32 GCD per minute**, or roughly 2.7 GCDs over the observed fight length. Total button presses were almost identical between groups.
2. Top players averaged about **43.84 seconds in Wanderer's Minuet**, **42.27 seconds in Mage's Ballad**, and **34.91 seconds in Army's Paeon**.
3. Top players converted more shared charges into Rain of Death when cleave was profitable, without materially changing total shared-charge usage.
4. Every sampled parse preserved five uses each of Raging Strikes, Battle Voice, Radiant Finale, Radiant Encore, and Barrage at the observed approximately 8.5-minute fight length.
5. A boss death around **20–30 seconds after the final party-buff anchor** was favorable because the full buff window contributed with little low-output tail.
6. Crit luck mattered, but it did not explain the ranking gap as strongly as GCD throughput.

There was no universal top-parse cast string. This is why the module uses priorities and conditional policies rather than replaying a fixed sequence.

## Runtime architecture

### Initialization and settings

`CielBard.lua` keeps the live config in memory (a deep copy of `CielBardData.Defaults` with saved overrides applied) and passes it to `CielBardEngine.Init`. MMOMinion's `Settings` object is a database-backed proxy that rejects populated tables and proxy re-assignment ("I was too lazy to implement a copy function for the DB-Settings Table"), so the config is mirrored to `Settings.CielBard` as flat primitive keys such as `abilities.ApexArrow`. GUI helpers call `markDirty()`; `flushIfDirty` writes changed keys at most once per second. `tests/run_gui_tests.py` imitates the proxy and fails if a table is ever assigned into it.

### ACR profile

`CielBard/acr/CielBard.lua` is a drop-in stub for `LuaMods/ACR/CombatRoutines/` that returns `CielBardACRProfile()` from the module (the same pattern the bundled MCR stub uses). Load order is not guaranteed, so when the module has not loaded yet the stub returns a lazy placeholder instead of an inert one: it already advertises `classes = { [23] = true }` and the name `CielBard`, every lifecycle method (`Cast`, `Draw`, `DrawHeader`, `DrawFooter`, `OnOpen`, `OnLoad`, `OnClick`, `OnUpdate`) resolves `CielBardACRProfile` at call time and delegates once it exists, and any other field is read through by `__index`. Delegation tolerates both `profile:Method()` and `profile.Method()` call conventions. `tests/run_gui_tests.py` evaluates the stub in a runtime where `CielBard.lua` has not been loaded and then proves `Cast()` drives the engine after the module loads. The profile's `Cast()` calls `CielBardEngine.Step(true)`, where ACR's Enabled toggle is the master switch and `config.enabled` is ignored. `Draw()` reuses the standalone window; `OnOpen()` maps to ACR's Profile Options. When `ACR.IsActive()` reports the CielBard profile, the standalone `Gameloop.Update` and `Gameloop.Draw` handlers stand down so the engine is never driven twice.

The three registered handlers are:

- `Module.Initalize` → initialization.
- `Gameloop.Update` → rotation pulse.
- `Gameloop.Draw` → configuration and diagnostics window.

The manifest intentionally spells `Module.Initalize` the way MMOMinion expects it.

### Capability layer

Every optional combat action is defined in `CielBardData.AbilityDefaults` and checked through:

```lua
CielBardEngine.AbilityEnabled(key)
```

This is the central rule for customization. Do not add isolated checkbox checks throughout the engine. New optional abilities should be added to the defaults table, exposed in the GUI if appropriate, and gated through `AbilityEnabled` at their decision point.

When `advancedEnabled` is false, the optimized defaults are authoritative. Old or unusual saved custom settings cannot affect normal users. Utility automation is false in the optimized defaults.

### Update loop

`CielBardEngine.OnUpdate` performs the following sequence:

1. Verify the module is enabled and pulse timing permits work.
2. Require a living Bard player and reject loading, locked, or casting states.
3. Optionally require combat.
4. Validate the target, range, and line of sight.
5. Observe the last cast to update weave, burst, and song state.
6. Update the rolling TTK estimate.
7. Count nearby enemies.
8. Build a normalized decision context.
9. Prefer a ready GCD over every oGCD.
10. Respect Full, GCD-only, or oGCD-only execution mode.

Strict GCD priority is intentional and reflects the clearest research result.

## Priority behavior

### GCD priority

The current broad order is:

1. Establish enabled DoTs when expected lifetime justifies them.
2. Consume enabled transformed/proc actions: Blast Arrow, Resonant Arrow, and buff-window Radiant Encore.
3. Use Apex Arrow at its context-sensitive gauge threshold unless it should be pooled for an imminent enabled burst.
4. Snapshot or refresh both DoTs with Iron Jaws when enabled and legal.
5. If Iron Jaws is disabled or only one DoT is enabled, refresh enabled DoTs individually.
6. Consume remaining Radiant Encore, Shadowbite (at its own target threshold, which is higher while Barrage is active), and Refulgent Arrow procs.
7. Apply or refresh DoTs on a secondary engaged enemy when multi-dot is enabled.
8. Use Ladonsbite when its target threshold is met.
9. Use Burst Shot.
10. Fall back to Heavy Shot for level sync.

Burst Shot and Heavy Shot are deliberately non-configurable safety fillers. The master execution switch is the supported way to stop all offensive execution.

### oGCD priority

The engine first enforces the configured weave limit, then broadly prioritizes:

1. Enabled utility whose rule is currently satisfied.
2. Song start or enabled-song transition.
3. Starting an available enabled burst package when the song condition and the configured DoT gate permit it. With potion use on, the potion is weaved first in the same window so Raging Strikes follows it.
4. During burst: Battle Voice, Radiant Finale (only with at least one tracked coda), Barrage, Pitch Perfect, Empyreal Arrow, Sidewinder, and shared-charge spenders.
5. Outside burst: Pitch Perfect overcap/song-end protection, Empyreal Arrow on cooldown unless briefly held, then near-cap shared charges unless held for burst.

Refulgent Arrow is normally cleared before Barrage. If Refulgent itself is disabled, Barrage is allowed to proceed rather than waiting forever.

### Songs

The optimized cycle is:

```text
Wanderer's Minuet → Mage's Ballad → Army's Paeon → repeat
```

Default remaining-time transition thresholds are approximately:

| Current song | Swap with this much remaining |
|---|---:|
| Wanderer's Minuet | 1.2s |
| Mage's Ballad | 2.7s |
| Army's Paeon | 10.1s |

These values translate the empirical active durations from nominal 45-second songs. If one song is disabled, `nextEnabledSong` constructs a legal cycle from the remaining songs. If all songs are disabled, song automation returns safely and the GUI reports a warning.

### DoTs

Stormbite and Caustic Bite are established only when expected target lifetime exceeds `dotMinimumTTK`, default 18 seconds. Iron Jaws refreshes both near expiration and may take a late-buff snapshot if enough fight duration remains.

If Iron Jaws is disabled, the engine individually refreshes each enabled DoT. If both DoTs are disabled or the target is near death, direct-damage GCDs continue normally.

#### Multi-dot

`multiDot` (**default off since 0.5.2**; also off in the Conservative, No DoTs, and Single target presets) keeps both enabled DoTs on up to `multiDotMaxTargets` additional enemies. Candidates come from `EntityList("alive,attackable,incombat,maxdistance=25")`, must be targetable, in line of sight, and at or above `multiDotMinHPPercent`, and are ranked by current HP so the longest-lived adds are dotted first. Secondary DoTs sit after proc consumption and before Ladonsbite/Burst Shot in the GCD order, are suppressed in the terminal and ideal-finish bands, and are cast directly on the entity so the player's current target never changes. Iron Jaws is used on a secondary target when both DoTs are present and one is expiring.

The default became off in 0.5.2 on the 0.5.1 review's High #3 finding: eligibility is the primary target's TTK plus an HP-percent floor, with no per-target TTK estimate and no potency-payback calculation, so on an ordinary three-to-five-target pack the engine can spend several GCDs applying DoTs to adds that die before the DoTs repay the AoE potency given up. The feature stays available for durable boss adds. `TIMING_VERSION` was bumped to 4 and `migrateTiming` clears a saved `multiDot = true` once, so existing installs pick the new default up but a user who switches it back on keeps it. It becomes a default again once one of these exists: per-target TTK estimates, an exactly-two-target policy, encounter/add whitelisting, a potency-payback calculation, or a multi-target simulator damage model.

#### Burst DoT gate

`burstDotGate` controls what Raging Strikes waits for: `NONE`, `ONE` (default: at least one enabled DoT is active), or `BOTH` (the v0.3 behavior, used by the Conservative preset). The gate is bypassed in the terminal band and when TTK is below `dotMinimumTTK`. `ONE` reproduces the standard opener where Raging Strikes follows the first DoT and Caustic Bite lands under it.

### Burst and resource pooling

The engine treats any enabled Raging Strikes, Battle Voice, or Radiant Finale as a configured major burst anchor. If Raging Strikes is disabled, Battle Voice or Radiant Finale can establish the local burst window so related priorities still function.

Pooling occurs only when it serves an enabled future burst:

- Apex is held inside the configured horizon unless gauge approaches overcap.
- Empyreal Arrow receives only a short pre-burst hold.
- Shared-charge spenders receive a longer pre-burst hold while still protecting against charge loss.
- Disabling all major burst actions removes those burst-specific holds.

### Radiant Finale and codas

Codas are tracked locally in `state.codas` from every observed or requested song cast and cleared whenever Radiant Finale is observed or requested. They are not read from the gauge because the array layout is unverified. `E.RadiantFinaleAllowed` enforces:

- Never request Radiant Finale at zero codas (the game would reject it and the engine would spam a failed request).
- Fire at one coda in the opener; holding for more codas loses a use over the fight, so `radiantFinaleMinCodas` defaults to 1 and the GUI warns when it is raised.
- If the next enabled song is due within `radiantFinaleCodaHold` seconds (default 2.0) and would add a new coda, let the song land first. Skipped in the terminal and ideal-finish bands.

### Potion

`usePotion` is off by default because it consumes inventory. When on, `E.RefreshPotion` scans (at most every five seconds) for the potions in `CielBardData.Potions`, newest grade first and HQ (`id + 1000000`) before NQ, using FFXIVMinion's `GetItem(hqid, bags)` helper or a direct `Inventory:Get(bag):GetItem(slot)` scan. `E.TryPotion` calls `item:Cast(Player.id)`, counts the animation lock as one weave, and ignores the later `lastcastid` echo for that item action. The potion is requested only when a burst is startable in the current weave window and a second weave slot remains for Raging Strikes, unless `potionOnlyWithBurst` is off. It is skipped when TTK is below `potionMinimumTTK`. Because the potion recast is 270 seconds and bursts are 120 seconds apart, the natural alignment is opener, 6:00, and 12:00.

### AoE

`useAOE` is the master switch; `aoeTargets` holds a per-action nearby-target threshold for `Ladonsbite`, `Shadowbite`, and `RainOfDeath` (all default 2) plus `ShadowbiteBarrage` (default 3). Enemies are counted within five yalms of the current target. With current potencies (Ladonsbite 140 per target vs Burst Shot 220, Shadowbite 200 vs Refulgent 280, Rain of Death 100 vs Heartbreak Shot 180) every replacement is a gain at two targets, but the thresholds stay separate because Shadowbite and Rain of Death use a five-yalm circle while Ladonsbite is a cone. `E.AoEAllowed(key, ctx)` is the single gate for these actions.

#### Barrage-aware Shadowbite

Shadowbite and Refulgent Arrow consume the same Hawk's Eye proc, and Barrage changes which one wins. Barrage makes the next Refulgent Arrow strike three times (280 x 3 = 840) but only raises Shadowbite's potency to 300 per target (it is **not** a triple hit). So:

| Targets | Ordinary proc | Barrage proc |
|---|---|---|
| 2 | Shadowbite 400 vs Refulgent 280 -> **Shadowbite** | Shadowbite 600 vs Refulgent 840 -> **Refulgent** |
| 3 | Shadowbite 600 -> **Shadowbite** | Shadowbite 900 vs Refulgent 840 -> **Shadowbite** |

`E.ShadowbiteAllowed(ctx)` therefore replaces `E.AoEAllowed("Shadowbite", ctx)` in the GCD order, and `E.ShadowbiteTargetsRequired()` returns `aoeTargets.ShadowbiteBarrage` while Barrage is active and `aoeTargets.Shadowbite` otherwise. `E.BarrageActive()` prefers the live status (`buffRemaining(Player, actionStatusID(A.Barrage), Player.id) > 0`, the same helpers song detection uses); builds that do not expose `statusgainedid` fall back to a local timer started by an accepted `E.TryCast(A.Barrage, ...)` or by `E.ObserveLastCast` seeing a Barrage cast, with the window taken from `CielBardData.BarrageWindowSeconds` (10).

Target counting and encounter-specific target selection require live validation.

## Kill-time model

The automatic estimator samples target HP percentage, fits a local linear slope over the configured sample window, smooths the estimate, and exposes a confidence score. Automatic terminal behavior is suppressed until confidence meets `minimumTTKConfidence`, default 0.50. Manual TTK is available for controlled testing and encounters where HP slope is misleading.

The policies are:

| Band | Meaning | Current intent |
|---|---|---|
| `LEARNING` | Automatic estimate is not trusted yet. | Use sustainable behavior. |
| `TERMINAL` | Expected death is within `terminalTTK`, default 20s. | Dump enabled resources and avoid low-payback DoTs. |
| `IDEAL_FINISH` | Expected death is 20–30s away. | Complete burst, then empty short-term resources. |
| `EXTENDED_TAIL` | Expected death is 31–60s away. | Burst fully but maintain sustainable post-burst play. |
| `SUSTAIN` | More than 60s remains or no trusted finite estimate exists. | Preserve long-run uses and normal maintenance. |

The estimator can be distorted by phase transitions, invulnerability, shields, healing, adds, or target swaps. A future version should model TTK as a confidence-weighted range and incorporate encounter phase information rather than relying solely on linear HP decay.

## Advanced customization

Normal users can ignore the entire advanced panel. The optimized behavior remains active until **Enable custom settings** is selected.

Available presets:

| Preset | Behavior |
|---|---|
| Optimized | Restores all optimized defaults. |
| Conservative | One weave, no late-buff snapshot, no terminal dump, and no burst pooling. |
| No party buffs | Disables Battle Voice and Radiant Finale. |
| No DoTs | Disables both DoTs and Iron Jaws. |
| Single target | Disables AoE behavior and AoE actions. |
| GCD only | Runs only the GCD side of the engine. |

Manual changes mark the configuration as `Custom`.

Toggle categories:

- Songs.
- DoTs and Iron Jaws snapshotting.
- Burst buffs and Barrage.
- Gauge and proc actions.
- Damage oGCDs and shared-charge variants.
- AoE behavior.
- Utility and HP thresholds.
- Resource pooling, terminal dumping, line-of-sight requirements, and execution mode.

Dependency conflicts are non-fatal. The GUI warns about impossible or ineffective combinations such as Blast enabled while Apex is disabled, but the runtime always proceeds to the best legal enabled action.

## Utility automation

Utility is opt-in and intentionally conservative:

- Second Wind uses a configurable self-HP threshold.
- Nature's Minne currently targets self below a configurable HP threshold.
- Troubadour uses a configurable self-HP threshold as a simple defensive heuristic.
- Warden's Paean attempts to detect a dispellable player debuff.

These rules are scaffolding, not encounter-grade utility logic. Warden's debuff-field detection, target rules, and defensive timing must be checked live. Future support should allow party targeting, encounter timelines, and user-defined utility rules.

## Configuration warnings and safeguards

`CielBardEngine.GetConfigurationWarnings` currently reports:

- All songs disabled.
- Blast enabled while Apex is disabled.
- Resonant enabled while Barrage is disabled.
- Radiant Encore enabled while Radiant Finale is disabled.
- Iron Jaws enabled without both DoTs.
- Multi-dot enabled with both DoTs off.
- Radiant Finale minimum codas above 1.
- Potion use enabled with no Gemdraught of Dexterity found (shown even outside advanced mode).
- oGCD-only mode without an internal GCD driver.

Runtime safeguards include:

- Execution off by default.
- Job, alive, loading, lock, cast, combat, target, range, and LOS checks.
- Request throttling.
- Configurable maximum weaves.
- GCD-first scheduling.
- Permanent Burst Shot/Heavy Shot fallback.
- Disabled dependencies never block downstream legal actions.
- TTK confidence gating.

## Animation lock: what was learned

The MMOMinion Lua API cannot change the client's animation lock. The sandbox has no FFI, no `require`, and no process launching; `Hacks` has no lock function; and the encrypted "core" addons on the store (MadaoCore, CypherCore, and others) are pure Lua libraries. Rikudou's "Zero Ping Enabled" works because his TensorCore ships a native DLL loaded through `MinionFiles`, a partner arrangement with MMOMinion. Measured on a dummy with the CielProbe cast logger, his option cut oGCD-to-oGCD gaps from a 719 ms median to 640 ms and in some cases below 440 ms, which is under the real server lock.

Decision: CielBard does not ship a lock hack. The READMEs recommend XivAlexander (standalone) or NoClippy (Dalamud) as optional companions; both stay above the real server lock. CielBard's pulse (30 ms) and request throttle (60 ms) were tightened in 0.4.1 so it benefits automatically. A native CielBard component is only worth pursuing if MMOMinion grants a partner DLL slot; a request has been sent. The `tools/CielProbe` module is the read-only API dumper and cast-timing logger used for this investigation.

## Installation and first live test

1. Copy the complete `CielBard` folder into the FFXIVMinion/MMOMinion `LuaMods` directory.
2. Confirm `CielBard/module.def` is directly inside that folder.
3. Reload Lua modules or restart MMOMinion.
4. Change to Bard and open the Ciel Bard window.
5. Leave execution disabled.
6. On a training dummy, expand **Gauge diagnostics**.
7. Identify the gauge entry that moves from 0 to 100 with Soul Voice and the entry that moves from 0 to 3 with Wanderer's Repertoire.
8. Correct the configured gauge indexes if necessary.
9. Enable execution only after diagnostics look correct.

Validate in this order:

1. The module loads without Lua errors.
2. The master switch starts and stops all requests.
3. No GCD pauses occur on a valid stationary target.
4. Both DoTs apply and Iron Jaws refreshes them.
5. Song state is detected and transitions occur near configured thresholds.
6. Refulgent clears before Barrage.
7. Apex does not overcap and Blast follows legally.
8. Burst buffs align without repeated failed requests.
9. Weave count and animation lock do not cause clipping.
10. Each advanced toggle skips its action without stalling.
11. GCD-only and oGCD-only modes stay within their boundaries.
12. AoE replacements occur only at the configured target count.
13. TTK confidence and policy bands behave sensibly.
14. Utilities remain off unless deliberately enabled.

Start with a training dummy. Do not use the module in duties until the above behavior is confirmed.

## Offline tests

Run from the repository root:

```bash
python -m pip install -r tests/requirements.txt
python tests/run_mock_tests.py
python tests/run_gui_tests.py
```

`run_gui_tests.py` loads the GUI file against a mocked DB-settings proxy and checks flat persistence, reload round-trips, and the ACR profile contract. `run_mock_tests.py` currently verifies:

- All Lua source files parse.
- Optimized damage defaults remain active when advanced mode is off.
- Utilities remain opt-in.
- Apex Off falls through to Burst Shot even at full gauge.
- All songs Off safely performs no song action and produces a warning.
- Iron Jaws Off uses individual DoT refreshes.
- No-DoT configurations continue direct damage.
- Heavy Shot remains the final level-sync fallback.
- GCD-only mode cannot emit an oGCD while the GCD is locked.
- Ladonsbite, Shadowbite, and Rain of Death each honor their own target threshold, and Shadowbite honors the higher Barrage threshold from either the live status or the fallback timer.
- An accepted request is not re-sent for `requestDedupeMs` unless a new cast is observed or the client reports the action on cooldown; a rejected request clears the guard at once.
- The burst DoT gate behaves correctly in NONE, ONE, and BOTH modes.
- Codas accumulate from observed songs and clear on Radiant Finale; Finale is never requested at zero codas, fires at one coda, holds for an imminent coda-adding song, and ignores the hold in the terminal band.
- The potion is weaved before Raging Strikes with HQ preferred, counts as a weave, and is skipped when off, on cooldown, missing (with a warning), or under the TTK floor.
- Multi-dot is off in the shipped defaults; when switched on it applies Stormbite to an engaged secondary target, uses Iron Jaws when both DoTs are expiring there, and skips idle, low-HP, or already-dotted targets, kill-near bands, and the Off toggle; procs still win.
- `tests/run_gui_tests.py` additionally covers the Optimized-preset full reset, the `multiDot` migration running exactly once, and the ACR stub under reverse load order.

Add a regression case whenever a new toggle, dependency, or fallback branch is introduced.

## Important implementation assumptions to verify

The following depend on undocumented or version-sensitive MMOMinion behavior:

- `Player.gauge` indexes for Soul Voice, Repertoire, and song timer.
- `ActionList:Get(1, id)` readiness and transformed-action behavior.
- `statusgainedid` for song detection.
- `Player.castinginfo.lastcastid` and `timesincecast` semantics.
- Cooldown representation as `cdmax - cd`.
- `highlighted` for Refulgent proc detection.
- Buff ownership and duration fields.
- Dispellable-debuff field names used by Warden's Paean.
- `target.los`, distance, and entity-query behavior.
- How quickly last-cast observation updates relative to animation lock.
- The `incombat` EntityList filter and `entity.incombat` field used by multi-dot.
- `GetItem` / `Inventory:Get(bag):GetItem(slot)` results, `item.hqid`, `item:IsReady`, `item:Cast`, and whether the item action's `id` appears in `lastcastid` (potion weave accounting).
- Whether casting a DoT on a non-targeted entity changes the player's target on the live client.

Song tracking contains a local 45-second timer fallback if status detection is unavailable, but live status detection is preferred.

## Recommended next development steps

### Immediate: live-client stabilization

1. Load the current build on a training dummy with `debug` switched on (it ships off since 0.5.2).
2. Record the actual Bard gauge layout.
3. Confirm song status IDs and local-timer fallback behavior.
4. Measure action-request timing, animation lock, and weave counting.
5. Validate every transformed action and proc readiness check.
6. Fix any API-field mismatches before expanding features.

### Next: observability

1. Add an optional decision trace showing considered actions and rejection reasons.
2. Record action requests, observed casts, GCD gaps, proc losses, overcaps, and buff alignment.
3. Add an exportable session report so dummy and encounter runs can be compared to FFLogs.
4. Display effective capability state and dependency resolution in the UI.

### Then: rotation quality

1. Calibrate opener and two-minute sequencing from live state rather than static assumptions.
2. Improve charge tracking and overcap prediction.
3. Model expected Apex generation before the next burst.
4. Add party-buff awareness where MMOMinion exposes it reliably.
5. Improve AoE target valuation using target-level potency rather than a simple count, and estimate per-add time to kill for multi-dot instead of the HP-percent floor.
6. Read codas from the gauge once its layout is calibrated, as a cross-check for the local tracker.
7. Make TTK phase-aware and resistant to downtime or target swaps.
8. Add a fight-ending score that compares DoT, direct GCD, and resource-dump value.

### Finally: usability

1. Add import/export for presets.
2. Allow named user presets.
3. Add contextual tooltips explaining what each toggle changes.
4. Add a read-only recommendation mode that displays the next action without casting.
5. Package a clean release archive after live validation.

## Coding guidance

- Preserve the centralized capability layer.
- Keep decision code deterministic and observable.
- Prefer safe continuation over repeated attempts at an unavailable action.
- Never allow an optional configuration to remove the final filler fallback.
- Treat lost GCDs and lost major cooldown uses as more severe than small ordering imperfections.
- Keep encounter-specific heuristics separate from the generic Bard engine.
- Add tests alongside behavior changes.
- Do not commit FFLogs secrets, `.env` files, raw event exports, local client dumps, or screenshots containing credentials.
- Keep execution disabled by default in every preset and migration.

## Credentials and data safety

FFLogs tools read credentials only from environment variables:

```bash
export FFLOGS_CLIENT_ID='...'
export FFLOGS_CLIENT_SECRET='...'
```

Never hard-code credentials or paste them into committed commands, test fixtures, reports, or screenshots. If a secret has been shared in chat or an image, rotate it before future collection work.

## External references

- MMOMinion Lua API: <https://wiki.mmominion.com/doku.php?id=lua_api>
- MMOMinion GUI API: <https://wiki.mmominion.com/doku.php?id=gui_api>
- MinionLib: <https://wiki.mmominion.com/doku.php?id=minionlib>
- FFXIVMinion reference repository: <https://github.com/MINIONBOTS/FFXIVMinion>
- FFLogs: <https://www.fflogs.com/>

## Definition of done for the next milestone

The next milestone should not be called stable until:

- A complete training-dummy session runs without Lua errors or repeated failed casts.
- Gauge, song, proc, cooldown, and weave state are confirmed on the live client.
- The GCD remains continuously active under normal stationary conditions.
- All optimized-default actions and every advanced toggle have been exercised.
- TTK policies can be observed switching without erratic oscillation.
- No credentials or raw private data appear in version control.
- Offline regression tests pass after all live-client fixes.

## Engine changes made from simulator findings (0.5.1)

Applied from `sim/output/FINDINGS.md`, verified with a 200-seed 510 s A/B on identical seeds (25,805 -> 26,074 DPS, +1.04%, >6 sigma; Empyreal 30.0 -> 33.3 casts, Iron Jaws 10.65 -> 11.61, hard DoT re-applications 2.35 -> 1.36 per fight):

1. `nextBurstSeconds()` now returns the maximum remaining cooldown over the enabled burst buffs (time until the whole package is ready). The old minimum form started every pre-burst hold ~7.5 s early because Radiant Finale's 110 s recast leads Raging/Battle Voice.
2. Empyreal Arrow's pre-burst hold has its own key, `empyrealHoldForBurstSeconds`, defaulting to 0. The hold could never pay for itself (52 potency of buff value vs a 260-potency lost use).
3. `apexOffcycleGauge` 90 -> 80 (300 paired seeds: +0.25%, p = 0.0003; 100 was worst). `apexHoldForBurstSeconds` measured 0 effect and is left as is.
4. Iron Jaws urgency pre-empt ahead of the proc consumers, `dotUrgentSeconds = 1.5`, so Blast/Resonant/Encore/Apex chains cannot let both DoTs fall off.

Not changed on purpose: `maxWeaves`, `weaveMinGcdRemaining`, `dotRefreshSeconds`, Pitch Perfect rules (see FINDINGS.md section 3). The sim's engine hash pins in `tests/test_integration.py` were re-baselined for 0.5.1. `chargePoolSeconds` has since been re-swept on 0.5.2 now that `nextBurstSeconds` is no longer skewed - **25 stays** (FINDINGS.md 4.3).

## Engine changes made from the 0.5.1 code review (0.5.2)

`REVIEW_0.5.1.md` is the verified external review this release implements. The engine-side items:

1. **Barrage-aware Shadowbite (High #2).** `E.BarrageActive()`, `E.ShadowbiteTargetsRequired()`, and `E.ShadowbiteAllowed(ctx)` were added, and the GCD order now gates Shadowbite through the last of these. New setting `aoeTargets.ShadowbiteBarrage` (default 3) sits next to the Shadowbite slider in the window. See *Barrage-aware Shadowbite* above for the potency arithmetic and the detection fallback.
2. **`multiDot` default false (High #3)**, with a one-time migration at `TIMING_VERSION = 4`. The toggle and every preset are unchanged.
3. **ACR stub resilience (High #4).** `CielBard/acr/CielBard.lua` returns a lazy placeholder instead of an inert one; see the ACR section above.
4. **Pending-request dedupe (medium).** `E.TryCast` records the accepted action id, target, and tick, and suppresses an identical request for `requestDedupeMs` (default 350). The guard is cleared by `E.ObserveLastCast` seeing any new cast, by the client reporting the action `isoncd`, by the window expiring, and immediately by an explicit rejection from `Cast()`. This is the live-latency race the simulator cannot reproduce, because it flips readiness the instant a request is accepted.
5. **Optimized preset is a complete reset (medium).** `applyPreset` now restores every key in `CielBardData.Defaults` except the documented preserve list in `CielBard.PresetPreserved` (`enabled`, `showWindow`, `lockToolNoticeDismissed`, `timingVersion`, the three gauge indexes, and `advancedEnabled`), then merges the preset's own overrides on top.
6. **`debug` default false (medium).** The trace code itself is unchanged; only the default moved.

Item 1 of the review (simulator potencies) and the recalibration/sweep work belong to `sim/` and are not part of this change. Because the shipped Lua changed, the engine hash pins in `tests/test_integration.py` need re-baselining for 0.5.2.

The module table is now also exposed as the global `CielBardUI` (`CielBardUI.config`, `CielBardUI.ApplyPreset`, `CielBardUI.PresetPreserved`, `CielBardUI.drivenByACR`) so the offline harnesses can drive presets without reaching into a chunk-local table.

## Review response: REVIEW_0.5.1.md item by item

Every item in the verified external review, and what was done about it. "Engine" items are
0.5.2 changes under `CielBard/`; "simulator" items are 0.5.2 changes under `sim/`. Nothing
under `CielBard/` was modified by the simulator pass.

| review item | severity | what was done |
|---|---|---|
| **1. Simulator action potencies are outdated** | High | **Done (simulator).** `sim/data/job.json` and `actions.json` now carry the current job-guide values: Apex Arrow 140 at 20 gauge to 700 at 100, Blast Arrow 700 with 50% falloff, Resonant Arrow 640 with 50% falloff, Refulgent Arrow 280 / 840 under Barrage, Shadowbite 200 / 300 under Barrage, Ladonsbite 140, Radiant Encore 700 / 800 / 1100, Heavy Shot 160. Wide Volley (140 / 220) is absent from `CielBardData.Actions` and so has no record. Every data table was re-checked, not just the four the review named. Calibration re-fitted (`potency_to_damage` 132.40 -> **128.56**), the Apex sweep re-run at 300 paired seeds, and `sim/output/calibration.md`, `sweep_apex.md` and `FINDINGS.md` regenerated. |
| **2. Barrage plus Shadowbite is wrong at two targets** | High | **Done (engine + simulator).** `E.BarrageActive()`, `E.ShadowbiteTargetsRequired()` and `E.ShadowbiteAllowed(ctx)` added, with a new `aoeTargets.ShadowbiteBarrage` defaulting to 3 and a 10 s `CielBardData.BarrageWindowSeconds` fallback when the client does not expose the status. The simulator gained a multi-target damage model, and the fix is now **measured**, not argued: at two targets the engine fires Refulgent Arrow 2.85 times per fight (of 3.00 Barrages, 0.15 expired) and at three targets 0.00, with Shadowbite rising by exactly 2.84. Regression cases for all three scenarios are in the mocked-runtime suite. |
| **3. Multi-dotting should not be an optimized default** | High | **Done (engine).** `multiDot = false` in `CielBardData.Defaults` and in every preset, with a one-time migration at `TIMING_VERSION = 4`. The toggle itself is unchanged. The simulator **cannot yet retire this**: its multi-target model gives every enemy the primary's HP and no death time, so the payback calculation the review asks for has nothing to run on. `multiDot = false` should stay until per-target TTK exists on both sides. |
| **4. ACR stub does not recover from reverse load order** | High | **Done (engine).** `CielBard/acr/CielBard.lua` returns a lazy placeholder whose lifecycle methods delegate to `CielBardACRProfile` once it appears, instead of an inert one. Covered by a GUI/ACR test that evaluates the stub before `CielBard.lua` (`ACR stub reverse load order ok`). |
| Pending request deduplication | Medium | **Done (engine).** `E.TryCast` records the accepted action id, target and tick and suppresses an identical request for `requestDedupeMs` (default 350). Cleared by an observed cast, by the client reporting the action `isoncd`, by the window expiring, or immediately by an explicit rejection. **The simulator cannot exercise this** - it flips readiness the instant a request is accepted - so it has a mocked-runtime test instead. |
| Optimized preset is not a complete reset | Medium | **Done (engine).** `applyPreset` now restores every key in `CielBardData.Defaults` except the documented `CielBard.PresetPreserved` list, then merges the preset's own overrides. |
| Debug logging defaults to enabled | Medium | **Done (engine).** `debug = false`. The trace code is unchanged. |
| Generated reports and documentation are inconsistent | Medium | **Done.** `sim/output/FINDINGS.md` no longer claims its proposed engine changes are unmade - it records that the 0.5.1 changes shipped and adds the 0.5.2 re-run. `sim/README.md` gained a "Repository output policy" section and `.gitignore` now excludes per-seed and intermediate JSON. **Known remaining drift:** `sim/README.md` still says `calibration.md` has to be re-run before its numbers are quoted, and that `FINDINGS.md` and `sweep_apex.md` predate the Patch 7.5 corrections. All three have now been re-run and their staleness banners removed; that paragraph needs a one-line correction. `empyreal_report.md` and `pp_ironjaws_report.md` **do** still carry their banners correctly - their diagnoses stand and their fixes shipped, but their DPS numbers were taken on the old curve and have not been re-measured. |
| Recalibrate and re-run the sweeps | (fix order 6) | **Done.** Calibration re-run at 150 seeds per duration anchor; the Apex grid re-run at 300 paired seeds per point; `chargePoolSeconds` re-swept at 300 paired seeds now that `nextBurstSeconds()` is unskewed. Results and the recommended-defaults table are in `sim/output/FINDINGS.md` section 4. |
| Add two-, three- and five-target scenarios | (fix order 7) | **Partly done.** 1, 2 and 3-target 300 s batches at 300 seeds each are in `sim/output/multitarget.csv`; five targets has not been run. |

**The one setting change this pass recommends and did not make:** `apexHoldForBurstSeconds`
35 -> 0. It measures +0.128% at gauge 80 over 300 paired seeds, p = 0.0524 - positive at
every gauge where the hold can act, never negative in any run, and 0 is the simpler default,
but not a significant result. `apexOffcycleGauge = 80` is confirmed under the corrected
curve (+0.237% over 90, p = 0.000079) and `chargePoolSeconds = 25` is confirmed best of
{0, 15, 25, 35}. See `sim/output/FINDINGS.md` 4.5.

## Simulator

`sim/` is a level-100 Bard training-dummy simulator that **drives the shipped Lua engine
rather than re-implementing it**. `sim/client.py` publishes a fake MMOMinion API into a
`lupa` `LuaRuntime`, loads `CielBard/CielBard_Data.lua` and `CielBard/CielBard_Rotation.lua`
verbatim, and calls `CielBardEngine.Step(false)` once per pulse; `sim/core.py` owns the
clock, the event queue and every game rule. The engine's decisions are the thing under
test, so nothing under `CielBard/` is ever modified - `tests/test_integration.py` pins both
files by sha256. The fake client reproduces the live-client cooldown semantics recorded in
this handoff (elapsed `cd` against total `cdmax`, `cdmax = recast x maxCharges` for charged
actions, `IsReady` false for self-targeted actions against an enemy id, gauge indices 4 and
2). Every fight is deterministic given a seed, in the same process or a different one.

### What exists

| path | contents |
|---|---|
| `sim/SPEC.md` | the complete contract: module ownership, public signatures, the pulse loop, cooldown semantics, the calibration procedure |
| `sim/README.md` | how to install and run it, plus "things that will look like bugs and are not" |
| `sim/MECHANICS_CORRECTIONS.md` | job-guide and Balance corrections that override SPEC where they disagree, and the parse-study-derived hypotheses |
| `sim/data/*.json` | every potency, duration, recast, proc rate and status id. No mechanic constant lives in code |
| `sim/output/calibration.md` | the calibration report (generated head, hand-written analysis below the `# Analysis` marker) |
| **`sim/output/FINDINGS.md`** | **start here.** The decision-oriented digest for this repository's maintainer, re-run for 0.5.2: what the corrections changed, the status of every recommended engine change (all shipped), the re-run Apex / charge-pool / multi-target results, the recommended defaults table, and the assumptions still unverified |
| `sim/output/sweep_apex.md` | the Apex verdict, re-run on the Patch 7.5 curve: `apexOffcycleGauge` {80, 90, 100} x `apexHoldForBurstSeconds` {0, 35} at 300 paired seeds per point, with `sweep_apex.csv` beside it |
| `sim/output/sweep_chargepool.csv` | `chargePoolSeconds` {0, 15, 25, 35} at 300 paired seeds, re-run after the `nextBurstSeconds()` fix |
| `sim/output/multitarget.csv` | the 1 / 2 / 3-target 300 s batches at 300 seeds each: the Barrage-aware Shadowbite threshold measured in casts |
| `sim/output/empyreal_report.md` | per-pulse attribution of every wasted Empyreal second, the root cause on `CielBard_Rotation.lua:958`, the isolation proof, and the engine change written out (`empyreal_reasons.csv`, `empyreal_paired.csv`) |
| `sim/output/pp_ironjaws_report.md` | the Pitch Perfect stack budget (balances - not a defect) and the Iron Jaws DoT fall-off defect, with `diag_pp_ij.py`, `sweep_dots.csv`, `sweep_dots_nokill.csv`, `sweep_terminaldump400.csv` |
| `tests/test_*.py`, `tests/run_sim_tests.py` | unit and integration suites, plain `unittest`, no pytest |

### How to run it

Everything runs as a module from the repository root, with the Python 3.12 interpreter that
has `lupa` (a bare `python` on the dev box is the Microsoft Store stub).

```bash
# one fight
python -m sim.run --seconds 510 --seed 1 --kill-time 510

# a seed range, aggregated to mean / sd / p05 / p50 / p95
python -m sim.batch --seconds 510 --seeds 1-200 --workers 11 --json sim/output/batch.json

# a configuration axis (engine config keys, plus ping_ms / pulse_ms / seconds)
python -m sim.sweep --seconds 510 --kill-time 510 --seeds 1-150 --workers 11 \
  --axis "resourcePooling=true,false" --csv sim/output/sweep.csv

# refit the potency -> damage scalar against the 40 Vamp Fatale parses
python -m sim.calibrate --seeds 1-150 --workers 11 --out sim/output/calibration.md

# tests
python tests/run_sim_tests.py
```

`--kill-time SECONDS` is the flag worth knowing: without it the target is a striking dummy
that never dies and the engine's TTK estimator never reaches its terminal band. Pass it
when comparing against kill parses; leave it off for sustained dummy DPS. Read `sweep`
output with its `dps_sem` column beside `delta` - at 510 s, neighbouring points routinely
differ by less than the batch standard error.

### Calibration result (engine 0.5.2, Patch 7.5 potencies)

**Re-run after the potency corrections and the 0.5.1/0.5.2 engine changes.** Fitted
`potency_to_damage = 128.5594` (from an uncalibrated 100.0) over seeds 1-150 across the
five duration anchors, residual mean absolute error 0.98%, max 2.85% across the 40 parses.
The scalar is fitted as `sum(aDPS) / sum(sim DPS)`, so it moves inversely with potency:
132.40 -> 128.56 is the +3.0% of simulated potency the corrected Apex / Blast / Resonant
values added. On that scale the engine at its shipped defaults simulates **1.37% below the
top-10 mean aDPS of 34,633** (34,158.9 +- 34.0 at 510 s, 300 seeds, no kill window).

**The rotation-shape agreement improved sharply**, which is the part a scalar cannot fake.
Casts per minute at the 520 s anchor against the merged report's top-10 means:

| action /min | 0.5.0, old potencies | 0.5.2, corrected | top-10 |
|---|---:|---:|---:|
| Empyreal Arrow | 3.462 (-12.1%) | **3.923 (-0.3%)** | 3.937 |
| Iron Jaws | 1.232 (-5.8%) | **1.343 (+2.7%)** | 1.308 |
| charge spenders (combined) | 7.292 (-1.3%) | **7.427 (+0.6%)** | 7.384 |
| Pitch Perfect | 2.678 (-4.8%) | 2.655 (-5.6%) | 2.814 |
| Apex Arrow | 0.959 (-1.4%) | 1.065 (+9.5%) | 0.973 |
| all casts | 43.071 (-4.9%) | 43.623 (-3.6%) | 45.270 |

The two changes 0.5.1 made for this reason landed: the Empyreal count gap is gone and Iron
Jaws now slightly overshoots rather than undershooting. The Pitch Perfect gap is the known
`sim.calibrate` artefact (it sets no `kill_time_s`, so the terminal one-stack dump never
fires). The **Apex overshoot is new and is the one number to watch**: `apexOffcycleGauge`
is now 80, which fires more and smaller Apex Arrows than the parses show. See the cast-rate
discussion in `sim/output/sweep_apex.md`.

**The 0.5.2 sweeps, and the defaults they recommend** (nothing under `CielBard/` was
modified by the simulator pass; these are reported, not applied):

1. **`apexOffcycleGauge = 80` is confirmed under the 140-700 curve.** 80 beats 90 by
   **+0.237%** at hold 0 (300 paired seeds, t(299) = +4.00, p = 0.000079, 95% CI +0.121%
   to +0.354%) and by +0.132% at hold 35 (p = 0.029). Gauge 100 moved off the bottom -
   it is now second, indistinguishable from 80 (p = 0.156) and ahead of 90 (p = 0.048).
2. **`apexHoldForBurstSeconds` 35 -> 0 is recommended but not proven.** +0.128% at gauge
   80, p = 0.0524, CI -0.001% to +0.257%. Positive in sign at every gauge where the hold
   can act, never measured negative, and 0 is the simpler default - but 300 seeds do not
   resolve it and it should not be quoted as significant.
3. **`chargePoolSeconds = 25` stays.** Re-swept over {0, 15, 25, 35} now that
   `nextBurstSeconds()` is no longer skewed: 25 wins, 0 loses -0.173% (p = 0.034), 15 loses
   -0.143% (p = 0.020), 35 loses -0.079% (p = 0.373, inside noise). The 0.5.0 collapse at
   35 is gone - it cost 5.6 Heartbreak casts then and costs 1.0 now, which is the skew fix
   showing up exactly where it was predicted to.

Read `sim/output/FINDINGS.md` first - it is the ranked decision list with confidences and
the remaining unverified assumptions. `sim/output/calibration.md` has the full per-action
disagreement analysis; `sim/output/sweep_apex.md` is the Apex investigation, re-run for
0.5.2. `empyreal_report.md` and `pp_ironjaws_report.md` still carry their 0.5.0 staleness
banners: their diagnoses stand and their fixes shipped, but their DPS numbers were measured
on the old potency curve and have not been re-taken.

### Known limitations

- **Raw parse replay is not possible.** Only `bard-analysis/output/killtime/killtime.csv`
  (40 rows of aDPS, duration and kill timing) and the aggregate counts in
  `merged-report.md` survive; the raw FFLogs event streams are not on disk. Calibration is
  therefore simulated DPS against parse aDPS as a function of fight length, plus per-action
  *rates* against the merged report's top-10 means. There is no per-parse rotation to diff
  against, and no way to recover gauge or Repertoire state from the parses.
- **One multiplicative scalar cannot correct a rotation-shape error.** Its mean residual is
  zero by construction; the model's R^2 against a constant-mean null is 0.03. Judge the
  rotation from the per-action rate table, never from the DPS number.
- **The scalar absorbs things that are not stats**: external raid buffs in aDPS, the
  parses' real movement and downtime against a stationary dummy, the potion (all 40 parses
  used one, the simulator does not by default - measured at +1.08% over 150 seeds, 5.7
  sigma), and Bard auto attacks
  (`stats.auto_attack_dps` ships at 0.0, worth 7-10% of real aDPS). Auto attacks in
  particular are absorbed as a multiple of potency rather than of time, which biases any
  experiment that moves GCD count without moving potency: ping, downtime windows, GCD_ONLY.
- **Multi-target is modelled but idealised.** Ladonsbite, Shadowbite and Rain of Death hit
  every clustered target with no falloff, and Blast Arrow, Resonant Arrow and Radiant
  Encore take the 50% falloff after the first, so *replacement thresholds* can now be
  measured - `sim/output/multitarget.csv` is the 1 / 2 / 3-target evidence for the
  Barrage-aware Shadowbite rule. What the model does **not** have is a per-target
  time-to-kill: every extra enemy has the primary's HP, stands inside the 5 yalm cluster
  radius, and never dies. That is why `multiDot` cannot be evaluated here and stays off by
  default, and why the multi-target DPS figures are a clustered-pack ceiling rather than a
  trash pull.
- **Utility casts are not modelled** (Warden's Paean, Troubadour, Nature's Minne, Repelling
  Shot), which is most of the residual 0.65 casts/min gap against the parses.
- Several mechanics are simulator assumptions rather than verified facts - the Army's Muse
  haste table, the Apex potency floor, non-DoT status ids, Radiant Encore's 700/800/1100,
  Repertoire procs modelled on the song timer independently of DoT presence, and Barrage's
  triple hit (`statuses.json` `weaponskill_hits = 3`, spent on the next
  `multi_hit_eligible` weaponskill, which is the model for which weaponskills Barrage may
  multiply). All of them are listed under "Unverified assumptions" in the calibration
  report, and any of them can be changed by editing JSON under `sim/data/`.
- Two SPEC scenarios are unreachable by the shipped engine and are documented instead of
  papered over: the 150 ms ping oGCD reduction (arithmetically impossible below ~350 ms)
  and the potion landing before Raging Strikes on the opener (the song takes the first
  weave slot). See "Known mechanic mismatches" in `sim/README.md`.

## Machinist module (CielMachinist 0.2.0)

`CielMachinist/` is a second installable module for level-100 Machinist. The decisions that shaped it:

- **Same repository, separate module.** It shares `tests/` and `tools/` with CielBard but installs on its own into `LuaMods/CielMachinist`.
- **Copy and adapt, not a shared core.** The job-agnostic machinery (guards, `TryCast` and the pending-request guard, weave limits, the TTK estimator, AoE counting, potion handling, flat settings persistence, presets, the ACR profile and its lazy stub) was copied from the live-proven Bard files rather than extracted, so CielBard was not touched and each module stays standalone. Extract a shared core only once both are stable live; until then a fix in that machinery has to be made in both modules.
- **Job guide and The Balance first.** Potencies and IDs were verified against the official job guide (Patch 7.5) and the xivapi Action/Status sheets; rotation rules follow The Balance's level-100 opener, static two-minute burst, FAQ and AoE tables. No parse study yet. Its simulator is the separate `sim_mch/` package (see below).

### Files

| Path | Purpose |
|---|---|
| `CielMachinist/CielMachinist_Data.lua` | Action/status IDs, defaults, capabilities, AoE thresholds, presets. |
| `CielMachinist/CielMachinist_Rotation.lua` | Engine: state, procs, charges, combo, tools, Hypercharge/Wildfire, Queen, priorities. |
| `CielMachinist/CielMachinist.lua` | Init, flat settings persistence, presets, window, ACR profile. |
| `CielMachinist/acr/CielMachinist.lua` | Lazy ACR stub for `LuaMods/ACR/CombatRoutines/`. |
| `sim_mch/` | Simulator: JSON data tables, `fakeclient.lua`, pricing, `run` and `sweep` CLIs, `output/FINDINGS.md`. |
| `tests/run_mch_mock_tests.py` | Lua parsing, static priority cases, and the timeline test driven through `sim_mch`. |
| `tests/test_mch_sim.py` | Simulator unit tests; ids in the JSON tables are checked against the shipped Lua. |
| `tests/run_mch_gui_tests.py` | Settings proxy, presets, ACR profile and stub, and coexistence with CielBard in one Lua state. |

### Engine design

Globals are `CielMachinistData`, `CielMachinistEngine`, `CielMachinistUI`, `CielMachinistACRProfile`; settings live under `Settings.CielMachinist`. `E.AbilityEnabled(key)` is the single capability gate, exactly as in CielBard.

**GCD order:** Blazing Shot / Auto Crossbow (only ready while Overheated) -> Air Anchor -> Drill at full charges -> Chain Saw -> Excavator -> Drill (or Bioblaster at 3+ targets with its DoT down) -> Full Metal Field -> short GCD hold for an imminent Air Anchor / Chain Saw (`toolHoldSeconds`, 0.4) -> Scattergun at 3+ -> Heated combo -> Split Shot fallback.

**oGCD order:** utility -> potion + Barrel Stabilizer -> Wildfire -> Hypercharge -> Reassemble -> Queen Overdrive (terminal only) -> Automaton Queen -> Double Check / Checkmate.

- **Burst anchor.** `nextBurst` is Barrel Stabilizer's cooldown (Wildfire's only when Barrel Stabilizer is Off). Wildfire trails the anchor by about thirteen seconds in the opener and therefore in every burst after it; using the maximum of the two, as CielBard does for its buffs, made every pre-burst hold thirteen seconds late.
- **Hypercharge** (`E.HyperchargeAllowed`) is blocked by `E.ToolsBlockHypercharge(8)`: Air Anchor or Chain Saw due inside the Overheated window, a Drill stack that would cap, or a pending Excavator / Full Metal Field. It is held when Wildfire is within `hyperchargeHoldForBurstSeconds` (12) but not yet up, and every hold is bypassed when the Hypercharged buff has 4 s or less left.
- **Wildfire** (`E.WildfireAllowed`) goes out directly behind Hypercharge and only into a window with at least `wildfireMinimumStacks` (3) Blazing Shots left. The first design weaved it one weaponskill *ahead* of Hypercharge, as in The Balance's standard opener; the timeline test measured 5 hits instead of 6 because the early weave slot left the fifth Blazing Shot 0.4 s outside the window. Hypercharge -> Wildfire gives six hits with 1.2 s of slack and is the placement The Balance calls the most ping-friendly.
- **Weave limit** follows the last weaponskill, not the Overheated status: one weave after Blazing Shot / Heat Blast / Auto Crossbow, `maxWeaves` otherwise, so Hypercharge and Wildfire can share the 2.5 s window.
- **Procs** (Overheated, Full Metal Machinist, Excavator Ready, Reassembled, Wildfire) use one helper, `procActive`: the live status wins; a timer started by the accepted or observed granting cast covers builds that expose the status late or not at all; once the status has been seen it is authoritative; the consuming cast clears the timer. Overheated additionally ends after five observed 1.5 s weaponskills.
- **Charges** (`chargeState`) generalises CielBard's Heartbreak model to Drill (2), Reassemble (2), Double Check (3) and Checkmate (3): `cdmax` = recast x max, `cd` elapsed, count = floor(cd / recast). `chargesAfterSpending` projects the stack at burst time for the Reassemble pool.
- **Combo** (`E.NextComboStep`): a highlighted Clean/Slug Shot first, then `Player.lastcomboid` / `Player.combotimeremain` (the fields FFXIVMinion's SkillMgr reads), then a local tracker fed by observed casts.
- **Reassemble** only when `E.NextTool` says a tool will be off its recast at least 0.2 s before the GCD is. Without that margin the timeline test caught it landing on Heated Slug Shot.
- **Automaton Queen** (`E.QueenAllowed`): potency is linear in battery, so the policy only avoids overcap and arrives at the burst full. Off-cycle at `queenBatteryOffcycle` (90); "last call" at any legal battery when `nextBurst` is within `queenRefillSeconds + queenLastCallSeconds` (42 + 10); kept inside the refill window unless full; inside the burst she waits up to `queenTopOffSeconds` (5.5) for a +20 tool that still fits. `E.GetBattery` reads at least 50 whenever the summon is ready, so a wrong gauge index cannot silence her.

### Added in 0.2.0

- **Pre-pull** (`E.TryPrepull`, `E.ArmPrepull`, settings `prepull`, `potionPrepull`). There is no countdown to read, so it runs only when the engine itself pulls (`requireCombat` off: Reassemble, potion, then the first weaponskill) or when the user arms it from the window's **Pre-pull now** button while waiting for someone else's pull (Reassemble and potion only; the engine never pulls in that mode, and the arm lapses after 10 s or on entering combat). Reassemble is only taken from a full stack.
- **Heat pooling** (`E.HeatPooledForBurst`, `hyperchargeBurstHeat`, `heatPerSecond`): an off-cycle, heat-funded Hypercharge is refused when `heat - 50 + heatPerSecond x nextBurst` would fall short of the target. Never applied to the free Hypercharge, inside the burst, in the terminal band, at a full gauge, or when the gauge reads under 50 while Hypercharge is ready (a miscalibrated index must not hold forever). **Ships Off (0)** because `sim_mch` measures 45 at -0.07% to -0.24% on average: the second Hypercharge starts about 0:23 into the burst, after a 20 s party window has closed, and banked heat may never be spent. Full table in `sim_mch/output/FINDINGS.md`.
- **Reassemble prediction** counts on Air Anchor and Chain Saw up to `toolHoldSeconds` after the GCD, because the GCD is held for them. Without that, a tool falling exactly on the GCD boundary was not seen and Reassemble sat capped for 30 s.
- **`sim_mch/`**, a separate simulator package. `sim/` was not extended because its core is songs, Repertoire and DoTs and its tests pin the Bard engine by hash. The fake client is Lua (`sim_mch/fakeclient.lua`) and data-driven from JSON; Python prices the cast log afterwards. Machinist has no random procs, so one fight per configuration gives exact differences in expected damage. The sweeps in FINDINGS.md confirm every shipped default as the best value tested (`toolHoldSeconds` 0.4 is worth +0.34%, holding Hypercharge for Wildfire +0.32%, summoning the Queen near the cap +0.30%).
- The fake client's clock starts at 100 s, not 0: `E.RefreshPotion` rate-limits its inventory scan against `Now()`, and at a zero clock the first five seconds never scanned, which hid the potion from the pre-pull.

### Calibration against real parses (2026-09-19)

`mch-analysis/collect.py` pulled the top 40 Machinist parses for Vamp Fatale and `sim_mch.calibrate` re-simulated each at its own length. The engine's weaponskill rate is within 0.6% of the top 10, every tool and two-minute cooldown within 0.7%, and **its opener is the most common top-10 opener, weaponskill for weaponskill**. The fitted scalar is 111.85 with a 0.81% mean residual, and the engine lands 1.20% under the top-10 mean. The Queen's hit timeline is now measured rather than assumed. The one placement that differs: top players weave Wildfire about 1.6 s *before* Hypercharge, the engine 0.6 s after; both get six hits offline. Details in `sim_mch/output/FINDINGS.md` section 0 and `sim_mch/output/calibration.md`.

### What the timeline test shows

`python tests/run_mch_mock_tests.py -v` prints it. With shipped defaults on the fake client (2.50 GCD, 0.6 s animation lock, no latency):

- Opener: Air Anchor [Barrel Stabilizer, Reassemble] Drill [DC, CM] Chain Saw [DC, CM] Excavator [Reassemble, Queen at 60] Drill [DC, CM] Full Metal Field [Hypercharge, Wildfire] Blazing Shot x5 with one weave each, Drill. This is The Balance's standard opener with Wildfire moved behind Hypercharge and the first Reassemble moved from pre-pull to the first weave.
- Six minutes: Wildfire 6/6/6 hits, 50 Blazing Shots in 10 Hypercharges, 0 heat and 0 battery wasted, no broken combo, GCD and Air Anchor never idle, never more than two weaves (one after Blazing Shot), Queens at 60 / 90 / 90 / 90 / 50 / 100 / 100.

The fake client enforces rules and logs casts; `sim_mch/core.py` prices the log (uncalibrated). Request latency is not modelled.

### Unverified on a live client

Everything in CielBard's *Important implementation assumptions* list, plus:

- `Player.gauge[1]` = Heat and `[2]` = Battery (from FFXIVMinion's bundled `Machinist_SHB.lua`, which predates Dawntrail).
- `Player.lastcomboid` / `combotimeremain` values for the Heated combo, and whether `highlighted` is set on combo-ready actions.
- Whether Drill, Air Anchor and Chain Saw report their **own** recast in `cd`/`cdmax` (assumed) rather than the shared GCD group, and whether Drill's two charges follow the `cdmax = recast x charges` layout Heartbreak Shot does.
- Whether a Blazing Shot shortens the combo filler's reported `cdmax` to 1.5 s; `E.GCDRemaining` reads the GCD from Heated Split Shot.
- How replaced actions (Hot Shot, Gauss Round, Ricochet, Heat Blast, Split Shot) report at level 100. The engine always tries the upgraded id first and never reads a replaced action's cooldown unless the upgrade is unusable.
- Status ids 851, 2688, 3864, 3865, 3866, 1946, 1866 appearing in `Player.buffs` / `target.buffs` with `ownerid` set.
- Whether Automaton Queen reports not-ready while a Queen is active.

### Next steps for Machinist

1. First live dummy session with `debug` on, following `CielMachinist/README.md`; fix API mismatches before anything else.
2. Revisit heat pooling once a live log shows where party buffs actually sit relative to the engine's burst; pulling Wildfire earlier would also change the answer.
3. Flamethrower, Dismantle / Tactician timing, Head Graze.
4. Try Wildfire ahead of Hypercharge on a live client (what top parses do) once weave timing there is known, and model request latency in the fake client so the simulator can judge it.
