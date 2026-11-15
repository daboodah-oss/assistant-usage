# Grok usage feed: current design and proposed redesign

Prepared by Keela, Sun Nov 15, 2026, 3:10 PM ET (rev 2: adds the incident report). Feed side only: no change to the data contract or the dashboard.

## 1. Current design (as running today)

### Pieces

| Piece | Where | Runs | What it does | Costs usage? |
|---|---|---|---|---|
| Usage tracker | `/workspace/grok-usage/grok_usage_tracker.py` on my computer | Plain background process, polls about every 5 min | Calls the Grok billing endpoint with the Grok CLI login (`~/.grok/auth.json`, auto-refreshed) and appends one JSON line per reading to `/workspace/grok-usage/usage_log.jsonl` | No |
| Collector | `lanes/grok/collect.py` | Called by the sampler routine | Takes the newest tracker reading (only if `ok`, has a %, and is under 20 min old) and appends rows to `data/grok/usage.csv`: one `weekly` row plus one `weekly_<product>` row per product | No (the script itself) |
| Grok Bot appender | `lanes/grok/append_grok_bot.py` | Called by the sampler routine | Appends one `window=grok_bot` row using the Grok Bot weekly % and reset, which the AI reads from the platform usage reading (not available to a plain script) | No (the script itself) |
| Change check | `push-grok.sh` | Called by the sampler routine | Compares the CSV's sha256 to `.last_pushed_sha` and prints UNCHANGED or CHANGED | No |
| Push | GitHub connector (`push_files`) | Called by the sampler routine | Commits the **whole** `data/grok/usage.csv` to `daboodah-oss/assistant-usage` main as `grok: sample <UTC>` | — |
| Sampler routine | AI routine "assistant-usage Grok lane sampler" | **Every hour** (was every 15 min until Nov 14) | Wakes an AI agent to run steps 1–4 above, read the Grok Bot %, push, and decide whether to alert | **Yes, every run** |
| Keep-alive routine | AI routine "Box bootstrap + keep-alive" | **Every hour** | Restarts the tracker if it died, plus box and pool health checks | **Yes, every run** |

### Data file today
- `data/grok/usage.csv`: 10,888 rows, about 1.47 MB, append-only, never trimmed.
- Rows by window: `weekly` 3,045; `weekly_GrokTasks` 2,073; `weekly_GrokImagine` 1,974; `weekly_GrokChat` 1,834; `weekly_GrokVoice` 1,628; `grok_bot` 319; `weekly_GrokBot` 15.
- About 5 of every 6 rows are per-product rows, and most of those are 0%.
- GitHub has no append operation, so every commit sends the whole file again.

### Incident: Grok STALE, Sun Nov 15, 2026 (1:00 PM to 3:02 PM ET)

**Symptom.** The dashboard showed Grok STALE. The last good commit was `3bd91cfa` ("grok: sample 2026-11-15T18:00:40Z", 1:00 PM ET). The weekly headline and the Grok Bot sub-block both stopped updating.

**Timeline (ET).**
- 1:00 PM: sampler run pushed `3bd91cfa` (1,465,235 bytes, `$file:` path form). OK.
- 1:04 to 1:58 PM: no tracker readings. The tracker's 5-minute timer pauses while the box is idle.
- 1:56 PM: sampler run. The newest tracker reading was 52 minutes old, so `collect.py` wrote no weekly rows (its freshness limit is 20 minutes). It appended one `grok_bot` row (6.3%). `push-grok.sh` printed CHANGED. The connector commit was **rejected**: the argument was over 1,048,576 bytes and the file is 1,465,491 bytes. `.last_pushed_sha` was not written. The routine reported failed; it stayed silent because that was the first failure in a row.
- 2:20 to about 3:01 PM: another gap in tracker readings while the box was idle.
- 2:59 PM: manual push `35ef3d27` (path form). It succeeded, sha256 `fe4546eb…` matches local, and it carried the 1:56 grok_bot row.
- 3:02 PM: the sampler routine's own run pushed `cfce769c` (1,465,982 bytes, sha256 `ce736f06…`, byte-identical to local). The newest rows on main are weekly 7% at 3:01:26 PM and grok_bot 7.1% at 3:01:44 PM. **Recovered.**

**Root cause 1: push.** The GitHub connector checks each argument's size (1 MiB cap) **before** it swaps a `$file:` path for the file's contents. Passing exactly `"$file:/path"` works at any size. This was proven at 1,465,491 bytes. The 1:56 run evidently passed the CSV text inline, or put other text around the `$file:` string, so no substitution happened. That run's transcript couldn't be opened, so which of the two isn't confirmed. The old routine step 4 said "commit the whole local file through the GitHub connector" without requiring the path form. The file crossed 1 MiB earlier this month, so any inline paste now fails.

**Root cause 2: stale tracker.** The tracker only produces readings while the box is awake. An hourly sampler that wakes the box often finds the newest reading older than 20 minutes and writes no weekly row.

**Other finding.** The remote file is byte-identical to local, CRs included. The newest 26 rows (from about 4:55 AM ET today) end in CRLF; older rows use LF. Something began writing CRLF. Data wasn't touched, and the source still needs to be investigated.

**Fixes applied (feed side only; data contract, dashboard, and tracker unchanged).**
- `push-grok.sh` (box only; backup `push-grok.sh.bak-20261115`): on CHANGED it writes the exact copy `.push_snapshot.csv` and prints its path and byte count. `--mark` records its sha256 in `.last_pushed_sha` and `.last_success_utc`.
- New `wait-tracker.sh` (box only, read-only): waits up to about 7 minutes for a tracker reading under 15 minutes old and prints FRESH or STALE. It always exits 0.
- Sampler routine prompt updated. Step 1 runs `wait-tracker.sh` before `collect.py`. Step 4 now requires `push_files` with `content` set to exactly `"$file:/workspace/assistant-usage/.push_snapshot.csv"`, never inline text, no line-ending conversion, no force-push. It runs `--mark` only after a commit sha comes back, and leaves `.last_pushed_sha` untouched on failure so the next run retries.
- Verification: routine commit `cfce769c` (3:02 PM ET) contains fresh weekly and grok_bot rows. The first run under the new prompt is due around 3:54 PM ET.

**Residual risks.** The hourly AI cost is unchanged, a wait of up to 7 minutes now adds a little to each run, the CRLF source is unknown, and `.push_content.txt` (1.46 MB, from 5:58 AM) is a leftover artifact.

### Why it burns usage
The work is trivial: three small scripts and one file upload. Even so, every hour a full AI agent wakes up and reads its instructions, runs tools, reads the output, handles the 1.4 MB upload and reasons about alerts. That's 24 sampler wakes plus 24 keep-alive wakes a day. The AI is acting as a cron job.

## 2. Proposed design

### Principle
Plain scripts do the scheduled, mechanical work for free. The AI runs only when judgment or a message to Jeff is needed.

### Pieces

| Piece | Runs | What it does | Costs usage? |
|---|---|---|---|
| Usage tracker (unchanged) | Plain process, every 5 min | Same as today | No |
| **Feed pusher (new)** | Plain script on a box timer, e.g. hourly | Runs `collect.py`, then `push-grok.sh`. If CHANGED, it commits `data/grok/usage.csv` with `git` over a **repo-scoped key** (a GitHub deploy key or fine-grained token limited to `daboodah-oss/assistant-usage`, contents write only). No size limit, no AI. It writes a one-line status file (last success, last error). | No |
| Tracker restart | Same timer | If the tracker isn't running, start it. That replaces the tracker part of the hourly AI keep-alive. | No |
| Grok Bot % (`grok_bot` rows) | Once a day in an existing AI run, or dropped | The Grok Bot weekly % is only readable by the AI, not by a script. Options are below. | Small or none |
| Freshness check | **Once a day**, AI | Reads the status file. Messages Jeff only if there's been no successful push for over 2 hours or the tracker has been stale for over 1 hour. Otherwise silent. | Small, 1 run a day |

### The `grok_bot` window: options for Jeff
- **A. Keep it, daily:** one AI read per day writes the `grok_bot` row. The dashboard number updates daily instead of hourly.
- **B. Use the tracker's `weekly_GrokBot` row:** since the Ultra switch, the billing endpoint already reports a GrokBot product % (for example 6% then 7% today) on the same reset. That's free and updates every 5 minutes, but it's whole-percent only and is a different source than the platform reading. I'd propose it only if you're OK with that difference. The contract stays the same; the `grok_bot` row would just be sourced differently, so this needs your OK.
- **C. Keep it hourly in AI:** today's cost, minus the push work.

My recommendation is A for now, and B after we compare the two numbers for a week.

### What Jeff would need to do
Create one GitHub fine-grained token, or approve a deploy key, limited to `daboodah-oss/assistant-usage` with Contents read/write. I'll give step-by-step clicks. It gets stored on my computer only (file mode 600) and never goes in the repo or chat.

### Optional, needs your OK because it changes the data contract
Stop writing all-zero per-product rows, or move history into monthly files. Either would keep the file small. Neither is needed once the push goes through git, so I'm **not** proposing it now.

## 3. Before / after / why

| | Before | After | Why |
|---|---|---|---|
| Sampler schedule | AI routine every hour | Plain box timer every hour; AI routine deleted or paused | Removes 24 AI wakes a day |
| Push method | GitHub connector, whole file per call, 1 MiB literal cap | `git push` with a repo-scoped key | Free, no size limit, reliable |
| Tracker restart | Hourly AI keep-alive | Same plain timer | Free. The AI keep-alive can be cut back to what's left of its pool checks. |
| `grok_bot` row | Hourly AI read | Option A (daily), B (free) or C (hourly) | Your call |
| Alerts | Hourly AI decides | Daily AI freshness check | Same coverage for staleness, far fewer wakes |
| Data contract / dashboard | — | Unchanged | Feed side only |

## 4. Rollout (after your OK)
1. You create the repo-scoped key. I install it and test one push.
2. I add the plain timer. It runs side by side with the AI sampler for 2 hours, and I confirm commits from both.
3. I pause the AI sampler, add the daily freshness check, and cut the keep-alive down.
4. I publish a change receipt and update `lanes/grok/README.md`.
5. Rollback: re-enable the AI sampler. Nothing else changes.

## 5. Review request for Budzilla (Sun Nov 15, 2026, 3:15 PM ET)
This is review only. Nothing activates until Jeff OKs it in his own words. Reply with findings labeled 1–5, and give any required changes as exact BEFORE/AFTER text.
1. **Incident:** do both root causes hold up (the 1 MiB cap is checked before `$file:` substitution, and tracker readings pause while the box is idle)? Are the applied fixes sufficient? Anything missed?
2. **CRLF:** does the dashboard parser handle mixed LF and CRLF lines? Should the CRLF source be fixed, and should the existing rows be left as they are?
3. **Redesign:** a plain box timer plus `git push` over a repo-scoped key, with a daily AI freshness check. Any security, reliability, or contract concerns? Is a deploy key or a fine-grained token the better choice?
4. **`grok_bot` window:** which option do you recommend, A, B, or C? Does B count as a contract change or only a source change?
5. Any other way to cut usage further without losing the freshness the dashboard needs.
