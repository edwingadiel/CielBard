# CielBard Development Handoff

## Project summary

CielBard is an experimental level-100 Bard rotation module for FFXIVMinion/MMOMinion. It was designed from an event-level analysis of the top 40 Bard parses for Vamp Fatale rather than from a single copied parse. The core conclusion was that high-end Bard play is a state-driven priority problem: procs, gauge, songs, target count, cooldown availability, and expected kill time change the best next action.

The current release is **v0.5.1**. It is an offline-tested, training-dummy MVP and has **not yet been validated in a live MMOMinion client**. Execution is disabled by default.

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
- Per-action AoE thresholds for Ladonsbite, Shadowbite, and Rain of Death.
- Configurable DoT gate (NONE / ONE / BOTH) before starting the two-minute burst.
- Multi-dot maintenance on additional engaged enemies, with a toggle.
- Lua parsing and mocked-runtime invariant tests.

Still required:

- Live MMOMinion validation.
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
| `CielBard/module.def` | MMOMinion module manifest; currently version 0.5.1. |
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

`CielBard/acr/CielBard.lua` is a drop-in stub for `LuaMods/ACR/CombatRoutines/` that returns `CielBardACRProfile()` from the module (the same pattern the bundled MCR stub uses). The profile's `Cast()` calls `CielBardEngine.Step(true)`, where ACR's Enabled toggle is the master switch and `config.enabled` is ignored. `Draw()` reuses the standalone window; `OnOpen()` maps to ACR's Profile Options. When `ACR.IsActive()` reports the CielBard profile, the standalone `Gameloop.Update` and `Gameloop.Draw` handlers stand down so the engine is never driven twice.

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
6. Consume remaining Radiant Encore, Shadowbite (at its own target threshold), and Refulgent Arrow procs.
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

`multiDot` (default on; off in the Conservative, No DoTs, and Single target presets) keeps both enabled DoTs on up to `multiDotMaxTargets` additional enemies. Candidates come from `EntityList("alive,attackable,incombat,maxdistance=25")`, must be targetable, in line of sight, and at or above `multiDotMinHPPercent`, and are ranked by current HP so the longest-lived adds are dotted first. Secondary DoTs sit after proc consumption and before Ladonsbite/Burst Shot in the GCD order, are suppressed in the terminal and ideal-finish bands, and are cast directly on the entity so the player's current target never changes. Iron Jaws is used on a secondary target when both DoTs are present and one is expiring.

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

`useAOE` is the master switch; `aoeTargets` holds a per-action nearby-target threshold for `Ladonsbite`, `Shadowbite`, and `RainOfDeath` (all default 2). Enemies are counted within five yalms of the current target. With current potencies (Ladonsbite 140 per target vs Burst Shot 220, Shadowbite 200 vs Refulgent 280, Rain of Death 100 vs Heartbreak Shot 180) every replacement is a gain at two targets, but the thresholds stay separate because Shadowbite and Rain of Death use a five-yalm circle while Ladonsbite is a cone. `E.AoEAllowed(key, ctx)` is the single gate for these actions.

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
- Ladonsbite, Shadowbite, and Rain of Death each honor their own target threshold.
- The burst DoT gate behaves correctly in NONE, ONE, and BOTH modes.
- Codas accumulate from observed songs and clear on Radiant Finale; Finale is never requested at zero codas, fires at one coda, holds for an imminent coda-adding song, and ignores the hold in the terminal band.
- The potion is weaved before Raging Strikes with HQ preferred, counts as a weave, and is skipped when off, on cooldown, missing (with a warning), or under the TTK floor.
- Multi-dot applies Stormbite to an engaged secondary target, uses Iron Jaws when both DoTs are expiring there, and skips idle, low-HP, or already-dotted targets, kill-near bands, and the Off toggle; procs still win.

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

1. Load v0.3 on a training dummy with debug logging.
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

Not changed on purpose: `maxWeaves`, `weaveMinGcdRemaining`, `dotRefreshSeconds`, Pitch Perfect rules (see FINDINGS.md section 3). `chargePoolSeconds` should be re-swept now that `nextBurstSeconds` is no longer skewed. The sim's engine hash pins in `tests/test_integration.py` were re-baselined for 0.5.1.

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
| **`sim/output/FINDINGS.md`** | **start here.** The decision-oriented digest for this repository's maintainer: what the mechanics corrections changed, the Apex verdict, the Empyreal / Pitch Perfect / Iron Jaws diagnoses, the recommended engine changes ranked by expected DPS gain with a confidence column, and the assumptions still unverified |
| `sim/output/sweep_apex.md` | `MECHANICS_CORRECTIONS.md` item 16 settled: the 9 x 60 grid plus the 300-paired-seed confirmation, with `sweep_apex.csv` / `.json` / `_confirm*.json` beside it |
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

### Calibration result

Fitted `potency_to_damage = 132.40` (from an uncalibrated 100.0) over seeds 1-150, residual
mean absolute error 0.99%, max 2.73% across the 40 parses; the kill-time bands were re-run
at 120 seeds each. On that scale the shipped engine simulates **1.33% below the top-10 mean
aDPS of 34,633**. The mechanics corrections (Barrage's triple hit) moved the scalar from
136.80 to 132.40, i.e. +3.3% simulated potency, and moved no per-action rate by as much as
1% - they changed what a cast is worth, not what the engine casts.

**Two engine changes are now measured well enough to make, and they are most of the gap.**
Both are described and not made; nothing under `CielBard/` has been modified.

1. **The pre-burst Empyreal Arrow hold, +0.67% to +0.75% (3.5-3.7 sigma).**
   `CielBard_Rotation.lua:958` holds Empyreal for a nominal 5 s before a burst, but
   `nextBurstSeconds()` returns 0 as soon as the *first* burst action is ready, so Radiant
   Finale's 110 s recast makes the hold ~15 s - exactly one Empyreal recast, lost once per
   two-minute window (30.0 casts per fight against the parses' 34.0). The fix is two parts:
   make `nextBurstSeconds()` take the maximum remaining cooldown over the enabled burst
   actions, and give the hold its own key `empyrealHoldForBurstSeconds` defaulting to 0.
   The first part also un-skews `chargePoolSeconds` and `apexHoldForBurstSeconds`, which are
   silently running ~7.5 s early.
2. **`apexOffcycleGauge` 90 -> 80, +0.25% (p = 0.0003 over 300 paired seeds).** The gauge
   carries the whole effect; `apexHoldForBurstSeconds` is worth nothing measurable at any
   value and gauge 100 is the worst of the three.

A third change, an Iron Jaws urgency pre-empt (`dotUrgentSeconds = 1.5`), is worth about
+0.16% - below what 150 seeds resolve, so it is a correctness fix to be verified on cast
counts. Pitch Perfect needs no change: its stack budget balances and the count gap is an
artefact of `sim.calibrate` not setting `kill_time_s`.

Read `sim/output/FINDINGS.md` first - it is the ranked decision list with confidences and
the remaining unverified assumptions. `sim/output/calibration.md` has the full
per-action disagreement analysis and the parameters still worth sweeping;
`sim/output/sweep_apex.md`, `empyreal_report.md` and `pp_ironjaws_report.md` are the
underlying investigations.

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
- **Single target only.** Rain of Death, Ladonsbite and Shadowbite have no multi-target
  damage model, so every shared charge is converted into Heartbreak Shot and the cleave
  optimisation the merged report identifies cannot be tested.
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
