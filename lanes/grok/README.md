# Grok lane (owner: Ara / Grok)

Samples Jeff's SuperGrok subscription via the xAI Grok CLI's own billing
endpoints. See `PROMPT.md` for the full build handoff.

- Spec: `PROMPT.md`
- Sampler: `collect.py` → `data/grok/usage.csv`
- Schedule: `.github/workflows/sample-grok.yml` (every 15 min)
- Secrets: `GROK_ACCESS_TOKEN`, `GROK_REFRESH_TOKEN` (GitHub Actions secrets)
