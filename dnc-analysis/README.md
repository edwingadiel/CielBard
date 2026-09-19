# Dancer parse study

Collects the top Dancer parses for one encounter from FFLogs and reduces them to `output/summary.json`, which `sim_dnc.calibrate` uses to fit the ally Esprit chance and the damage scalar and to compare the engine's rotation with what top players press.

```bash
export FFLOGS_CLIENT_ID='...'
export FFLOGS_CLIENT_SECRET='...'
python dnc-analysis/collect.py --top 40
python -m sim_dnc.calibrate --out sim_dnc/output/calibration.md --write
```

It shares its network layer with `mch-analysis/collect.py`; see that folder's README for how to create an FFLogs client. Raw event streams are cached under `output/events/` (git-ignored). `output/summary.json` holds per-parse aggregates and the public report code, and no character names.

Two quirks of Dancer logs that the summariser handles: a finish is logged twice (the cast, then its party-wide application), and a pre-pull potion has no cast inside the fight, so potions are counted from the Medicated buff.
