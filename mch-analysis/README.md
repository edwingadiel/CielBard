# Machinist parse study

Collects the top Machinist parses for one encounter from FFLogs and reduces them to `output/summary.json`, which `sim_mch.calibrate` uses to fit the simulator's damage scalar, measure the Automaton Queen's hit timeline, and compare the engine's rotation with what top players press.

```bash
# credentials come from the environment only; never put them in a file or a command history you share
export FFLOGS_CLIENT_ID='...'
export FFLOGS_CLIENT_SECRET='...'

python mch-analysis/collect.py --top 40            # encounter 101 (Vamp Fatale) by default
python -m sim_mch.calibrate --out sim_mch/output/calibration.md --write
```

PowerShell: `$env:FFLOGS_CLIENT_ID = "..."; $env:FFLOGS_CLIENT_SECRET = "..."`.

Create a client at <https://www.fflogs.com/api/clients/> (any name, any redirect URL; the client-credentials flow does not use it).

- Raw event streams are cached under `output/events/` and are git-ignored. `--summarise-only` rebuilds the summary from that cache without the network.
- `output/summary.json` is the only file meant for version control. It holds per-parse aggregates (duration, ranked DPS, casts, damage shares, Queen hit offsets, opener) plus the public report code, and no character names.
- A pre-pull potion has no cast inside the fight, so potions are counted from the Medicated buff.

`tests/test_mch_calibration.py` checks the summariser and the calibration end to end against simulator-generated data, without the network.
