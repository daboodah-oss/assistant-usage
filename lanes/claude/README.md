# Claude lane (owner: Fable / Claude)

Samples Jeff's Claude subscription via Anthropic's OAuth usage endpoint
(the same one Claude Code's `/usage` reads). See `PROMPT.md` for the full
build handoff.

- Spec: `PROMPT.md`
- Sampler: `collect.py` → `data/claude/usage.csv`
- Schedule: `.github/workflows/sample-claude.yml` (every 15 min)
- Secrets: `CLAUDE_ACCESS_TOKEN`, `CLAUDE_REFRESH_TOKEN` (GitHub Actions secrets)
