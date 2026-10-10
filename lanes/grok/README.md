# Grok lane (owner: Ara / Grok) — owner-hosted (deployment pattern B)

Ara's box already runs a usage tracker sampling the Grok billing endpoint
every 5 minutes (since Sep 30), with self-maintaining token refresh. The
lane converts the tracker's latest reading into `data/grok/usage.csv` per
the data contract; a 15-minute routine on Ara's box commits it.

- Spec: `PROMPT.md` (v2)
- Sampler: `collect.py` → `data/grok/usage.csv`
- Schedule: Ara's 15-minute routine (no GitHub workflow — the Grok refresh
  token rotates on every use and Actions cannot write rotated tokens back
  into repo secrets)
- Secrets: none in GitHub — tokens never leave Ara's computer
