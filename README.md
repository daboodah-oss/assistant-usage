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

## Installed app

The page is installable as a web app. In `manifest.webmanifest`,
`theme_color` and `background_color` are both `#0f1420` — the page's own
background colour (the `body` background in `site/build.py`) — so the
installed app's chrome and splash screen match the page. The manifest
deliberately has no `id`: the site is served from the shared host
`daboodah-oss.github.io`, where a relative `id` would resolve against the
host root, and adding any `id` would change the app's identity for copies
already installed. The maskable icon (`icons/icon-maskable-512.png`) is
generated from `icons/icon-512.png` by `tools/make_maskable.py`. There is
no service worker: the page has no install button and nothing that needs
offline caching, so the worker was retired — `sw.js` is a stub that
deletes the old caches and unregisters itself on clients that still have
it. The stub must stay served for at least 30 days after this lands;
after that, `sw.js` can be deleted.
