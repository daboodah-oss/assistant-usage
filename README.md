# Assistant Usage

One page showing Jeff's AI subscription usage across all three assistants:
**Muse** (Budzilla), **Claude** (Fable), **Grok** (Ara).

- Live page: https://daboodah-oss.github.io/assistant-usage/
- Each assistant owns one lane and samples its own platform's usage.
- GitHub Actions rebuilds the page whenever new data lands.

## Lanes

| Lane | Owner | Source | Deploy |
|------|-------|--------|--------|
| `lanes/muse/` | Budzilla (Muse) | `subscription-status` CLI on Budzilla's VM | B (Budzilla's VM) |
| `lanes/claude/` | Fable (Claude) | Anthropic OAuth usage endpoint (same one Claude Code `/usage` reads) | B (Jeff's PC) |
| `lanes/grok/` | Ara (Grok) | xAI Grok CLI billing endpoints | B (Ara's box) |

**Lane rule: never write outside your own `lanes/<name>/` and `data/<name>/`
directories.** The repo is the handoff surface — document everything so any
assistant can pick up any lane cold.

## Data

Each lane appends rows to `data/<lane>/usage.csv` per
[docs/DATA_CONTRACT.md](docs/DATA_CONTRACT.md). Secrets per
[docs/SECRETS.md](docs/SECRETS.md) — never committed, never logged.

## Site

`site/build.py` aggregates every `data/*/usage.csv` into a single `index.html`
(one panel per assistant, one combined chart).
`.github/workflows/build-site.yml` rebuilds and commits it on every data push;
GitHub Pages serves it from `main`.

## Picking this up cold

1. Read this README, `docs/DATA_CONTRACT.md`, `docs/SECRETS.md`.
2. Your lane's spec lives in `lanes/<name>/README.md`. The `PROMPT.md` files in
   the `claude`/`grok` lanes are the exact handoff prompts Jeff pastes to
   those assistants.
3. Branch protection is Tier 2: automation commits straight to `main`
   (force-pushes blocked, deletions restricted). Humans use PRs.

## Status

- [x] Repo scaffold + data contract (Budzilla)
- [x] Muse lane sampling, owner-hosted (Budzilla)
- [x] Claude lane sampling, owner-hosted on Jeff's PC (Fable — pattern B)
- [ ] Grok lane sampling, owner-hosted (Ara — see `lanes/grok/PROMPT.md`; no secrets or workflow needed)
