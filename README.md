# CielBard

Experimental level-100 rotation modules for FFXIVMinion/MMOMinion. The project started as a Bard engine built from an event-level study of the top 40 Bard parses for Vamp Fatale; the same priority-engine design now also drives a Machinist module.

## Repository layout

- `CielBard/` — installable Bard module (v0.5.2).
- `CielMachinist/` — installable Machinist module (v0.1.0).
- `sim/` — Bard training-dummy simulator that drives the shipped Bard Lua engine unmodified. Start with `sim/output/FINDINGS.md`.
- `bard-analysis/` — sanitized FFLogs collection and analysis scripts plus generated summary reports.
- `tests/` — offline suites for both modules and the simulator.
- `tools/CielProbe/` — read-only MMOMinion API dumper and cast-timing logger.
- `HANDOFF.md` — architecture, decisions, and the development log.

## Current status

**CielBard 0.5.2** has been run through its ACR profile on a live training dummy and behaved correctly. It has not been validated in duties. Execution is disabled by default.

**CielMachinist 0.1.0** is offline-tested only: mocked-runtime priority cases plus a time-stepped fake client that checks the opener and a six-minute fight against The Balance's level-100 rotation. It still needs its first live dummy session; see `CielMachinist/README.md` for the checklist.

Both modules keep the optimized setup as the zero-configuration experience. An opt-in advanced panel adds presets and per-ability Auto/Off controls; the engine recalculates holds, burst behavior, and fallback actions around the enabled set rather than assuming every button is available. They install side by side and share no globals or settings.

## Offline tests

```bash
python -m pip install -r tests/requirements.txt
python tests/run_mock_tests.py
python tests/run_gui_tests.py
python tests/run_sim_tests.py
python tests/run_mch_mock_tests.py
python tests/run_mch_gui_tests.py
```

## Analysis headline (Bard)

The top-40 sample did not reveal one universal perfect string. The strongest repeatable signals were higher GCD throughput, deliberate song allocation, correct AoE charge conversion, preservation of two-minute cooldown uses, and favorable kill timing. The engine therefore adapts to procs, resources, nearby targets, and estimated time to kill.

## Better weaving with an animation-lock tool

The modules need nothing extra, but weaving improves noticeably if you run [XivAlexander](https://github.com/Soreepeong/XivAlexander) (standalone) or [NoClippy](https://github.com/UnknownX7/NoClippy) (Dalamud) alongside the bot. They take your ping out of the client's animation lock, and the engines poll fast enough to use the shorter lock automatically.

## Credentials and raw data

FFLogs credentials are read from environment variables. Secrets, `.env` files, cached raw event exports, local reference checkouts, screenshots, and generated archives are intentionally excluded from version control.

## Disclaimer

Third-party automation may violate game rules or account terms. Use at your own risk.
