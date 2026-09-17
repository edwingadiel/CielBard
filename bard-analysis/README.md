# Bard Parse Analyzer

This working directory combines an event-level review of the top Vamp Fatale Bard parses with a separate kill-time model.

The kill-time analyzer measures boss death against the actual final Battle Voice/Radiant Finale casts. Credentials are read only from environment variables and are not written into outputs.

```bash
export FFLOGS_CLIENT_ID='...'
export FFLOGS_CLIENT_SECRET='...'
python killtime_analysis.py --top 40
```

Generated results are placed in `output/killtime/`.
