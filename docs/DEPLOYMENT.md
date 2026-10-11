# Lane deployment patterns

A lane's sampler must run every ~15 minutes and commit `data/<lane>/usage.csv`
per the data contract. Two patterns are allowed — pick the one that fits your
credentials:

## A. GitHub Actions (stateless-friendly credentials)

The sampler runs in `.github/workflows/sample-<lane>.yml`, reading secrets
that **do not change between runs** (API keys, non-rotating tokens). Nothing
to maintain, no credential state.

Use this only if your tokens never need to be written back. GitHub Actions
can *read* repo secrets but a workflow cannot *update* them, so any
rotating refresh token breaks this pattern at the first refresh.

## B. Owner-hosted (rotating or machine-bound credentials)

The sampler runs on the lane owner's own machine, where the login already
lives (a local CLI session, an OAuth token file, etc.). A scheduled routine
on that machine runs the sampler and commits `data/<lane>/usage.csv`.

- No tokens in GitHub, no lane workflow file needed.
- The owner's machine is responsible for keeping its own login alive
  (refresh logic, restart after rebuilds).

The `build-site` workflow triggers on any push to `data/**`, so both
patterns feed the page identically.

## Precedent

| Lane | Pattern | Why |
|------|---------|-----|
| `muse` | B (Budzilla's VM) | `subscription-status` CLI exists only there |
| `grok` | B (Ara's box) | Grok refresh token rotates on every use; Ara already runs a working tracker there |
| `claude` | B (Jeff's PC) | Claude Code refresh token rotates on every use |
