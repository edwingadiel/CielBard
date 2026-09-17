# CielBard

CielBard is an experimental level-100 Bard rotation module for FFXIVMinion/MMOMinion. It grew out of an event-level study of the top 40 Bard parses for Vamp Fatale and uses a priority engine rather than replaying one fixed sequence.

## Repository layout

- `CielBard/` — installable MMOMinion Lua module.
- `bard-analysis/` — sanitized FFLogs collection and analysis scripts plus generated summary reports.

## Current status

Version 0.4.0 is a training-dummy MVP. The Lua files pass offline parsing and mocked-runtime invariant tests, but the module has not yet been validated in a live MMOMinion client. Execution is disabled by default.

Version 0.4.0 adds opt-in Gemdraught of Dexterity use weaved before Raging Strikes, coda-aware Radiant Finale timing, per-action AoE target thresholds, a configurable DoT gate for the two-minute burst, and a multi-dot toggle that keeps DoTs on additional engaged enemies.

The optimized setup remains the zero-configuration experience. An opt-in advanced panel adds presets and per-ability Auto/Off controls; the engine recalculates holds, song cycles, DoT maintenance, burst behavior, and fallback actions around the enabled set rather than assuming every button is available.

Important live-test items are Bard gauge index calibration, song-state detection, animation-lock behavior, and encounter-specific target selection. See `CielBard/README.md` for installation and testing instructions.

## Analysis headline

The top-40 sample did not reveal one universal perfect string. The strongest repeatable signals were higher GCD throughput, deliberate song allocation, correct AoE charge conversion, preservation of two-minute cooldown uses, and favorable kill timing. The engine therefore adapts to procs, resources, nearby targets, and estimated time to kill.

## Credentials and raw data

FFLogs credentials are read from environment variables. Secrets, `.env` files, cached raw event exports, local reference checkouts, screenshots, and generated archives are intentionally excluded from version control.

## Disclaimer

Third-party automation may violate game rules or account terms. Use at your own risk.
