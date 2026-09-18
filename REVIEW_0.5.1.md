# CielBard v0.5.1 Review

Reviewed commit: [`811179a`](https://github.com/edwingadiel/CielBard/commit/811179a4cd26f1fe68b1f876f58f00b4949f3a1a)

## Executive summary

CielBard v0.5.1 is a substantial improvement over v0.3. The project now has a serious engineering foundation: live-client corrections, flat MMOMinion settings persistence, ACR integration, a diagnostic probe, and a deterministic simulator that executes the shipped Lua engine rather than duplicating its decisions in Python.

The architecture and test quality are unusually strong for an early rotation plugin. However, four issues should be addressed before the optimized configuration is trusted in live multi-target content:

1. The simulator contains outdated Patch 7.5 action potencies.
2. Shadowbite incorrectly wins over a Barrage-enhanced Refulgent Arrow at two targets.
3. Multi-dotting is too aggressive to be enabled by default.
4. The ACR stub can become permanently inert when loaded before the main module.

After correcting these, the simulator should be recalibrated and its optimization sweeps rerun. At that point, live-client behavior—not the overall architecture—will be the primary remaining risk.

## Priority findings

### 1. High: simulator action potencies are outdated

The simulator currently models:

| Action | Simulator | Current official Patch 7.5 value |
|---|---:|---:|
| Apex Arrow minimum | 100 | 140 |
| Apex Arrow maximum | 600 | 700 |
| Blast Arrow | 600 | 700 |
| Resonant Arrow | 600 | 640 |

Relevant files:

- [`sim/data/job.json`](https://github.com/edwingadiel/CielBard/blob/main/sim/data/job.json)
- [`sim/data/actions.json`](https://github.com/edwingadiel/CielBard/blob/main/sim/data/actions.json)
- [Official FFXIV Bard job guide](https://na.finalfantasyxiv.com/jobguide/bard/)

#### Impact

The simulator's exact `+1.04% DPS` result and its Apex-at-80 versus Apex-at-90 comparison were calculated with the older potency curve. The conclusion that Apex at 80 is preferable may still be correct, but the current sweep does not prove it for Patch 7.5.

The following recommendations are less sensitive to these potency errors and remain mechanically persuasive:

- Calculating the next burst from the maximum remaining cooldown across the enabled burst package.
- Giving Empyreal Arrow an independent hold duration that defaults to zero.
- Giving urgent Iron Jaws priority before a chain of proc GCDs can allow both DoTs to expire.

#### Recommended correction

1. Update the Apex curve, Blast Arrow, and Resonant Arrow values.
2. Search every simulator data table for additional Patch 7.5 potency changes.
3. Rerun calibration.
4. Rerun the Apex threshold and hold-duration sweeps with paired seeds.
5. Regenerate the checked-in findings and calibration reports.

### 2. High: Barrage plus Shadowbite is wrong at two targets

The engine checks Shadowbite before Refulgent Arrow whenever the Shadowbite target threshold is met:

- [`CielBard_Rotation.lua`, Shadowbite/Refulgent priority](https://github.com/edwingadiel/CielBard/blob/main/CielBard/CielBard_Rotation.lua#L794-L799)
- [`CielBard_Data.lua`, AoE thresholds](https://github.com/edwingadiel/CielBard/blob/main/CielBard/CielBard_Data.lua)

The default Shadowbite threshold is two targets. That is correct for an ordinary Hawk's Eye proc:

- Shadowbite: `200 × 2 = 400`
- Refulgent Arrow: `280`

It is incorrect while Barrage is active. The current official behavior is:

- Barrage-Refulgent Arrow: `280 × 3 = 840`
- Barrage-Shadowbite at two targets: `300 × 2 = 600`

At two targets, selecting Shadowbite under Barrage loses 240 potency. Shadowbite only becomes superior at three targets:

- Barrage-Shadowbite at three targets: `300 × 3 = 900`

#### Why the simulator missed it

The current simulator damage model is single-target and does not model Rain of Death, Ladonsbite, or Shadowbite cleave damage. Its tests can therefore verify action availability and single-target sequencing but cannot establish correct multi-target replacement thresholds.

#### Recommended correction

Use a dynamic Shadowbite threshold:

- Normal Hawk's Eye proc: two targets.
- Barrage-enhanced proc: three targets.

The engine will need a reliable way to know whether the current proc came from Barrage. This could be tracked from the accepted Barrage request or, preferably, confirmed from the live Barrage status when the MMOMinion status API is reliable.

Add regression cases for:

- Two targets, ordinary Hawk's Eye → Shadowbite.
- Two targets, Barrage active → Refulgent Arrow.
- Three targets, Barrage active → Shadowbite.

### 3. High: multi-dotting should not be an optimized default yet

Multi-dotting is enabled by default. Secondary DoT actions occur after proc consumption but before Ladonsbite:

- [`CielBard_Rotation.lua`, multi-dot priority](https://github.com/edwingadiel/CielBard/blob/main/CielBard/CielBard_Rotation.lua#L801-L806)

The current eligibility model uses:

- The primary target's estimated TTK.
- A minimum HP percentage for secondary targets.
- An engaged-enemy requirement to avoid pulling idle enemies.
- A configurable maximum number of secondary targets.

It does not estimate how long each secondary target will survive or compare the expected DoT payoff against repeated AoE GCDs.

#### Risk

On a normal three-to-five-target pack, the engine may spend several GCDs applying Stormbite and Caustic Bite to multiple secondary enemies before returning to Ladonsbite. Many trash enemies will die before the DoTs recover the AoE potency that was sacrificed.

The feature is valuable for durable boss adds, but that does not make it a safe universal default.

#### Recommended correction

Set `multiDot = false` in the optimized defaults until at least one of these is implemented:

- Per-target TTK estimates.
- An exactly-two-target multi-dot policy.
- Encounter/add whitelisting.
- A potency-payback calculation based on expected remaining DoT ticks.
- A multi-target simulator damage model.

If it remains enabled, it should at minimum be suppressed when the engine has three or more valid AoE targets unless the secondary target is explicitly known to live long enough.

### 4. High: the ACR stub does not recover from reverse load order

The drop-in ACR stub returns the real profile only when `CielBardACRProfile` already exists. Otherwise, it returns a placeholder with no supported classes and a `Cast` method that always returns false:

- [`CielBard/acr/CielBard.lua`](https://github.com/edwingadiel/CielBard/blob/main/CielBard/acr/CielBard.lua)

If ACR evaluates the stub before the main CielBard module finishes loading, the placeholder remains registered and never reconnects to the real profile.

#### Recommended correction

Either:

1. Make the placeholder lazy: its lifecycle methods should check for `CielBardACRProfile` and delegate once it becomes available.
2. Enforce the module load order and emit a visible error rather than silently registering an inert routine.
3. Trigger a deliberate ACR profile reload after CielBard initializes, if ACR provides a supported API for doing so.

Add a GUI/ACR test in which the stub is evaluated before `CielBard.lua`.

## Medium-priority concerns

### Pending request deduplication

The 30 ms pulse and 60 ms request throttle improve responsiveness. However, accepted action requests are not held in a pending state while waiting for the live client to update cooldown/readiness information.

If MMOMinion continues reporting an action as ready for more than 60 ms after `Cast` returns true, the same action may be requested repeatedly. The simulator changes readiness immediately after accepting a request, so it cannot reproduce this client-latency race.

Recommended approach:

- Record the accepted action ID and target.
- Suppress an identical request briefly—approximately 250–500 ms—or until a new observed cast/cooldown state confirms execution.
- Clear the pending state quickly when the client explicitly rejects or invalidates the action.

### Optimized preset is not a complete reset

The Optimized preset resets abilities and several major policy fields, but it does not restore every tuning, potion, utility-threshold, timing, or diagnostic setting to `CielBardData.Defaults`:

- [`applyPreset`](https://github.com/edwingadiel/CielBard/blob/main/CielBard/CielBard.lua#L276-L292)

Therefore, the documentation should not promise that Optimized restores every default unless the implementation performs a complete defaults reset while preserving only settings that are intentionally global, such as window visibility and the master execution switch.

### Debug logging defaults to enabled

`debug = true` is reasonable for the current live-test build, but it prints a detailed timing line every second. Change this to false before presenting the plugin as a normal release.

### Generated reports and documentation are inconsistent

- `sim/output/FINDINGS.md` says its proposed engine changes have not been made, but v0.5.1 applied them.
- `sim/README.md` says only `.gitkeep` is tracked under `sim/output`, while numerous generated calibration and sweep artifacts are committed.

Decide whether generated evidence is intended to be versioned. If it is, document that policy and keep only canonical reports. Large intermediate per-seed JSON files should generally be release artifacts or ignored files rather than permanent source history.

## Known, documented limitations

These are already acknowledged by the project and are not newly discovered regressions:

- The potion cannot always land immediately before opener Raging Strikes because the initial song occupies the first weave slot.
- A 150 ms simulated ping does not reduce oGCD count with the current GCD and animation-lock arithmetic.
- Gauge indexes, song status detection, charge fields, debuff fields, and animation-lock timing remain dependent on live MMOMinion behavior.
- The simulator currently represents a stationary single-target dummy and cannot validate encounter movement, target geometry, or AoE optimization.
- The automatic TTK model can be distorted by downtime, shields, invulnerability, healing, adds, and target swaps.

## What was done particularly well

### Simulator architecture

The simulator's strongest design choice is that it executes the actual shipped Lua engine through `lupa`. It does not reproduce the rotation rules in Python. This greatly reduces the chance that the simulator and production engine silently develop different priorities.

Other strong decisions include:

- Deterministic seeded execution.
- Data-driven action and status tables.
- Paired-seed A/B comparisons.
- Explicitly documented assumptions.
- Expected failures for impossible or intentionally unsupported scenarios.
- Hash/integration guards around the shipped engine.
- Separation of fake-client behavior, mechanics, damage calculation, reporting, and engine configuration.

### Live-client corrections

The following changes are evidence-based and improve practical reliability:

- Songs are requested on the player.
- LOS enforcement is opt-in because the live client reported false negatives.
- GCD timing uses observed `cd` and `cdmax` fields rather than trusting `IsReady` alone.
- Settings are persisted as flat primitive keys to accommodate MMOMinion's database-backed Settings proxy.
- Shared-charge behavior uses the charged-recast layout observed on the client.
- CielProbe records timing and inspects the live API surface.

### Rotation corrections

These changes are logically strong even before the potency tables are updated:

- `nextBurstSeconds()` now waits for the entire enabled burst package rather than treating the first ready buff as the burst start.
- Empyreal Arrow's hold is separated from generic resource pooling and defaults to zero.
- Urgent Iron Jaws can preempt a chain of proc GCDs before both DoTs fall off.
- Radiant Finale respects locally tracked codas and avoids zero-coda requests.
- Disabled capabilities continue through safe fallback actions rather than stalling.

## Test results

The following were run against commit `811179a`:

| Suite | Result |
|---|---|
| Lua syntax and mocked-runtime invariants | Passed |
| GUI, settings persistence, and ACR invariants | Passed |
| Simulator suite | 204 tests passed |
| Expected failures | 2, both documented |
| Median simulated decision pulse | Approximately 0.123 ms over 2,000 pulses |
| Example 60-second simulation wall time | Approximately 0.14–0.17 seconds |

The test coverage is excellent for the project's age. The largest remaining coverage gap is multi-target combat behavior.

## Recommended fix order

1. Update every simulator potency to current Patch 7.5 values.
2. Add dynamic Barrage/Refulgent/Shadowbite target logic.
3. Disable default multi-dotting until it has a payoff model.
4. Make the ACR stub resilient to reverse load order.
5. Add pending-request deduplication for live-client latency.
6. Rerun calibration and all paired-seed optimization sweeps.
7. Add two-, three-, and five-target simulator scenarios.
8. Reconcile generated reports and repository-output policy.
9. Disable default debug logging for a normal release.
10. Continue live training-dummy and encounter validation.

## Final assessment

The v0.5.1 update is an impressive piece of work and a major improvement over the initial MVP. Its architecture is no longer the primary concern. The most important issues are now narrower and fixable: current data accuracy, multi-target decision quality, one ACR lifecycle edge case, and live-client request timing.

Once the four high-priority findings are fixed and the simulator is rerun with current potency data, CielBard will have a strong foundation for serious live validation.
