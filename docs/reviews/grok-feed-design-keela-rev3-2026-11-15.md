# Grok usage feed: design rev 3 (approved design of record)

Sun Nov 15, 2026, 8:30 PM ET. Prepared by Keela.

Rev 3 documents the design **Jeff approved in his own words on Nov 15**. It is not a new approval
round. It supersedes rev 2 (`docs/reviews/grok-feed-design-keela-2026-11-15.md`, branch
`keela/grok-feed-design-2026-11-15`) and folds in Fable's review, Keela's response (PR #4), and
Fable's reply (`docs/reviews/grok-feed-design-fable-reply-to-keela-2026-11-15.md`, branch
`ccr-9b351626-4ebmm8`). Where Fable's reply recommends W1, Jeff ruled W2. Where it lists open
decisions, Jeff decided them (section 1).

All times are ET unless marked UTC. Feed side only: the data contract and the dashboard are
unchanged, except the grok_bot contract line that the comparison rule may amend later (section 6).

## 1. Jeff's ruling (Nov 15)

- The redesign is approved with R1 to R7 as amended by Keela's response, including the
  byte-prefix check added to R2's append-only guard. Fable's R8, R9 and R10 are folded in below
  exactly as he wrote them.
- **Wake plan W2:** one thin AI wake every 30 minutes. Its only job is to run `feed-run.sh` and
  stop. It replaces the sampler wake and the tracker part of the keep-alive wake.
- **Transport:** per R1 step 0(b), tested properly, including SSH through the box's proxy. Deploy
  key if SSH works, otherwise a fine-grained token over HTTPS.
- **Cutover:** per R3.
- **`collect.py`:** the box copy, with its `inferred_zero` tag, is committed to the repo as its own
  commit before the lane runs from the clone. Jeff rules on `inferred_zero` (contract rule 2) at
  that commit. Budzilla recommends ratifying it with a one-line contract amendment.
- **Plan label:** `grok_bot` rows use `PLAN = "Ultra"` in the script. `weekly` rows: record what the
  settings endpoint really returns. If the tracker turns out to be holding a stale value, fix the
  tracker first (section 5).
- **`grok_bot` source:** option A from the Nov 21 reset, with the platform-vs-billing comparison
  rule (section 6).

## 2. The one rule about time

**Nothing on the box runs while the box is hibernated.** The platform freezes the whole box when
no AI session is active, and every loop on it freezes too: the tracker, the heartbeat, and any timer.
This was measured with the heartbeat's `paused_s`: the box was frozen 56% of the time under hourly
sampling (Keela's response, 1.2). The 30-minute AI wake is the box's only clock, so the feed's
freshness is "about every 30 minutes".

AI wakes draw on the same usage pool they measure, so when the pool is exhausted no wake runs and
the feed goes dark (Nov 14, 11:52 AM to 9:57 PM ET). Only off-box checks can notice that: Budzilla's
weekly-row watch (live) and the healthchecks.io feed check (R7, section 4.3).

## 3. Incident record (corrected)

- **Nov 15, 1:00 to 3:02 PM ET, Grok STALE.** Two causes:
  - **Push:** the GitHub connector caps each argument at 1 MiB **before** `$file:` substitution. The
    1:56 PM run passed the 1.46 MB CSV in a form that wasn't substituted, so the push was rejected.
  - **Stale tracker:** the box was frozen between AI runs (2:00 PM heartbeat `paused_s=2642`, 3:03 PM
    `paused_s=2170`), so the newest reading was over 20 minutes old and `collect.py` wrote no weekly row.
  - Fixed the same afternoon. Verified by routine commit `cfce769c` (3:02 PM).
- **Nov 14 gap (11:52 AM to 9:57 PM ET):** the usage pool hit 99.9% at 11:51 AM ET, so no routine
  could run and the box stayed frozen. Feed commits resumed 15 minutes after Jeff switched to Ultra.
- **CRLF:** the box scripts always wrote CRLF (`csv.writer` default). Until the 3:57 AM ET Nov 15 run,
  AI runs stripped the CRs and passed `--plan Ultra` by hand. From 5:02 AM they stopped doing both.
  Nothing on the box changed at 4:55 AM. My earlier note "remote equals local minus CR" was true only
  while runs stripped CRs. R6 fixes the writers, and existing rows stay as they are.

## 4. Design as approved and built

### 4.1 Pieces

| Piece | Where | What it does | AI usage |
|---|---|---|---|
| 30-min wake | AI routine | Reads the platform Grok Bot weekly % and reset, runs `feed-run.sh`, then relays only `FAIL`, `ALERT` and `ACTION` lines. Otherwise silent | One thin wake |
| `lanes/grok/feed-run.sh` | Run from the transport clone `/workspace/assistant-usage-clone` | Holds a lock, sets up and fetches the clone, and loads this run's code from `origin/main`. Runs the box bootstrap and takes one reading. Appends weekly rows and the `grok_bot` row, records the comparison pair, pushes, and writes the status file. Sends the heartbeat ping if one is configured | None |
| `take_reading.py` | Repo | Takes one tracker poll under the tracker's `.poll.lock` (R8) | None |
| Tracker | `/workspace/grok-usage/grok_usage_tracker.py` (box only) | Reads Grok billing and settings. Loops every 5 min while awake. Every poll now holds `.poll.lock` | None |
| `collect.py` | Repo | Appends `weekly` and `weekly_<product>` rows. LF line endings | None |
| `append_grok_bot.py` | Repo | Appends the `grok_bot` row with `PLAN = "Ultra"` and `--source platform\|billing_product`. LF line endings | None |
| `grokbot_compare.py` | Repo | Runs the comparison rule (section 6). State lives on the box under `/workspace/grok-feed/state/grokbot-compare/` | None |
| `push_feed.py` | Repo | Pusher (R2, section 4.2) | None |
| `ssh_proxy.py` | Repo | SSH through the box's HTTP CONNECT egress proxy (R10) | None |
| Keep-alive | AI routine | Once a day (R9, section 7.2) | 1 wake a day |

Source of truth: the lane CSV `/workspace/assistant-usage/data/grok/usage.csv`. The clone is only
a transport vehicle and a code source. Status: `/workspace/grok-feed/state/status.json` and `status.log`.

### 4.2 R2 as amended (feed pusher), with R10's auth sentence

> It pushes through a separate transport clone, the way `lanes/muse/push_git.py` does: the local
> CSV stays the source of truth. Each of up to 3 attempts is a full cycle: fetch `origin/main`, reset
> the clone to it, copy the CSV in, stage only `data/grok/usage.csv`, commit, push to `main`. Never a
> force push. The staged diff is the only change check; `push-grok.sh` and `.last_pushed_sha` are not
> used. Before committing, `origin/main`'s CSV must be a byte-for-byte prefix of the local file
> (primary guard), the staged diff must be append-only (0 deleted lines), and the file must end in a
> newline; otherwise it pushes nothing and records the error. Every git call is non-interactive with a
> timeout, and the whole run holds a non-blocking lock so runs cannot overlap. On final failure the
> rows stay in the local CSV and the next run retries. No size limit, no AI.
>
> Auth: "a repo-scoped deploy key, or, if SSH cannot leave the box even
> through its HTTP proxy, a fine-grained token over HTTPS stored as a box
> secret. The token is never written into the remote URL or any log.
> R1(b) proves the chosen route with one authenticated `git ls-remote`
> before anything depends on it."

The code adds three more checks:
- Only that one path may be staged.
- The staged blob must be byte-identical to the local file, so no line-ending conversion can happen.
- The appended bytes must contain nothing that looks like a token.

### 4.3 R7 (freshness), plus the off-box heartbeat

> Reads the timestamp of the newest `window=weekly` row in `data/grok/usage.csv` on main as the
> primary signal, the same age the dashboard's STALE badge uses; the box status file is supporting
> detail only.

- Budzilla's off-box watch implements this. It is live and alerts when the newest weekly row is over 2 hours old.
- `feed-run.sh` can also ping a healthchecks.io check, so a dead box or an empty pool raises an off-box alarm:
  - A success ping on `OK`, `/fail` on `FAIL`, and nothing on `WARN`.
  - It reads the URL from the box secret `GROK_FEED_HC_URL`. If the secret is unset, it reports `hc=unset`.

**Heartbeat period and grace:** a 30-minute period with 90 minutes of grace. That turns the check red
about 2 hours after the last good run, which matches Budzilla's 2-hour watch and Fable's suggestion
(about 2 hours). Jeff creates the check and adds the secret. No outside account is created for him.

Side effect to plan for: the existing box heartbeat check (`HEALTHCHECK_URL`, pinged every 5 minutes
by the heartbeat loop) only pings while the box is awake. Under W2 the wakes last seconds, so that
check will go red often unless its grace is also set to about 2 hours.

### 4.4 R6 (line endings, plan)

Both writers use `csv.writer(f, lineterminator="\n")`, and existing CRLF rows stay as they are. The
pusher's byte-prefix guard keeps every existing byte unchanged. `PLAN = "Ultra"` is set in
`append_grok_bot.py`. The repo copy is the only copy: each run loads its code from `origin/main`.

## 5. Plan label: case found

Checked Sun Nov 15, 8:11 PM ET, with one read-only GET of the Grok settings endpoint
(`cli-chat-proxy.grok.com/v1/settings`) using the box's Grok login. No refresh was needed.

- **The endpoint really returns `subscription_tier_display = "SuperGrok Heavy"`** (HTTP 200).
  The tracker is not holding a stale value. Every tracker reading since Sep 30 carries the same
  value, and the live endpoint agrees today.
- **Case: "endpoint really returns Heavy".** `weekly` rows keep recording `SuperGrok Heavy`, and the tracker is unchanged for the label.
- `grok_bot` rows: `Ultra`, set in the script.
- For the record, the platform usage reading (the `grok_bot` source) says "Plan: Ultra" and 10.9%
  used of a weekly limit "shared with the other apps on their plan". It resets Sat Nov 21, 9:41 PM ET.
  The billing endpoint said 11% weekly, with GrokBot at 11%, at the same time.

## 6. `grok_bot` source rule (built in `grokbot_compare.py`; inactive until Nov 21)

- **From the Nov 21 reset** (Sat Nov 21, 9:41 PM ET = 2026-11-22T02:41:26Z), `grok_bot` rows come
  from the platform reading (option A). The wake passes the reading in, `feed-run.sh` appends the
  row, and the pusher pushes it.
- **What counts as a pair:** in the same `feed-run.sh` run, the platform % plus a billing reading that
  carries `products.GrokBot`, taken no more than 10 minutes apart. The billing `period_end` must
  equal the window's end. A billing reading without GrokBot is not a pair, because unknown is not zero.
  Pairs before the window go to `pre-window.jsonl` for information only.
- **At the window end (Nov 28, 9:41 PM ET):**
  - **Any pair differs by more than 1 point:** keep A, and report the divergent pairs to Jeff, with times and both values.
  - **Otherwise, 50 or more pairs:** switch to option B at that reset. One change amends the
    `grok_bot` line in `docs/DATA_CONTRACT.md` and sets `GROK_BOT_SOURCE=billing` in
    `lanes/grok/feed.conf`, so rows carry `raw` `source=billing_product`. Note the switch in the receipt.
  - **Fewer than 50 pairs:** extend one more week automatically. Pairs count cumulatively from Nov 21.
    A second extension is flagged for Keela.
- **How the decision surfaces:** `feed-run.sh` prints an `ACTION` line every run until Keela runs `grokbot_compare.py ack`.
- **Expected volume:** 48 wakes a day × 7 days is about 336 possible pairs, minus wakes skipped while the pool is exhausted.
- **Dry run today:** one pre-window pair, platform 10.9% vs billing 11.0% (diff −0.1).

## 7. Fable's R8, R9 and R10, as he wrote them, with the answers he asked for

Under Jeff's W2 ruling, "hourly" in R8 and R9 reads "every 30 minutes", and R9's "About 24 small
wakes" reads "About 48 small wakes". The rest is verbatim.

**R8.** Section 4, W1 row, "What wakes the box". AFTER:

> One hourly AI wake whose only job is to run `feed-run.sh` (take one
> reading now, under the same lock as any other use of the Grok login,
> then `collect.py`, then git push) and stop.  If a one-shot reading is
> not safe with the rotating login, `feed-run.sh` keeps the wait for the
> tracker loop and rev 3 says why.

**R9.** Section 4, W1 row, "Usage". AFTER:

> About 24 small wakes a day instead of 48 larger ones today.  The
> keep-alive's remaining pool checks do not keep an hourly wake of their
> own: they run inside this wake or once a day, and rev 3 states which.

**R10.** Section 3, R2 row, auth sentence. AFTER: as quoted in section 4.2.

### 7.1 One reading per wake (3a, R8): yes, it is safe, and it is built

- **The lock.** The tracker now takes a file lock, `/workspace/grok-usage/.poll.lock`, around every poll,
  including the token refresh. The patch was applied Nov 15, 8:13 PM ET, and the tracker was restarted.
  The backup is `grok_usage_tracker.py.bak-20261115`. `take_reading.py` imports the tracker and runs
  one poll under that same lock. A one-shot reading and the loop can therefore never both use the
  rotating refresh token at once. The refresh itself re-reads `auth.json` inside the lock.
- **Fallback.** If the tracker lacks the lock (an unpatched copy), `take_reading.py` does not poll. It
  waits up to 7 minutes for the loop instead and prints `why=tracker_has_no_poll_lock`.
- **Result.** `wait-tracker.sh`, the tracker-restart step and the 20-minute gate stop mattering. The
  reading is seconds old. A full run took 3 to 8 seconds in the dry runs.
- **Residual risk.** Anything else that uses the Grok login on the box, such as an interactive
  `grok` CLI session, does not take the lock. That risk is unchanged from today.

### 7.2 Keep-alive schedule in numbers (3c, R9): once a day

- **What moves into the wake.** `feed-run.sh` runs `/workspace/ops/box-bootstrap.sh` on every wake. That
  covers the timezone check, secret names, the heartbeat and tracker restarts, the boxchrome check, and
  reboot detection with its Telegram alert. All of these now run every 30 minutes at no extra wake
  cost. When boxchrome changes state, the wake prints `ALERT boxchrome up->down` (or `down->up`), and
  the wake relays it.
- **What the keep-alive keeps.** The keep-alive AI wake drops from 24 a day to **1 a day**. It keeps
  only the checks that need judgment, such as relaying ops and pool notes. It no longer restarts the
  tracker or runs bootstrap.
- **Totals.** Feed wakes: 48 a day, each a few seconds of script. Keep-alive: 1 a day. That is **49 wakes
  a day**, against 48 today (24 sampler wakes with up to 7 minutes of waiting plus a 1.4 MB connector
  push, and 24 keep-alive wakes).

### 7.3 Heartbeat period and grace (3e)

Period 30 minutes, grace 90 minutes, which alerts about 2 hours after the last good run (section 4.3).

### 7.4 Second independent Grok login (3d), for the record only

**Not verified.** Testing it would need a new `grok login`, which is an account action nobody has asked for.
- `~/.grok/auth.json` is keyed by issuer and principal, so the CLI's file format allows more than one entry.
- Whether a second device login gets an independent refresh-token family, so that two machines never
  burn each other's token, is unknown.
- The W3 decision comes after the comparison week, so this does not block anything.

## 8. Transport (R1 step 0(b)), tested Nov 15, 8:09 to 8:11 PM ET

| Route | Result |
|---|---|
| SSH `github.com:22`, direct | **Fails**: "Connection closed by 198.18.0.1 port 22" (no SSH banner) |
| SSH `ssh.github.com:443`, direct | **Fails**: "Connection closed by 198.18.0.1 port 443" |
| `HTTPS_PROXY` variable | Not set on the box. The box offers an unauthenticated HTTP CONNECT egress proxy at `SAND_EGRESS_TUNNEL_PROXY_ADDR` (127.0.0.1:8791) instead. Budzilla's `lanes/muse/ssh_proxy.py` requires proxy credentials in `HTTPS_PROXY`, so the grok lane carries a variant (`lanes/grok/ssh_proxy.py`) that falls back to that address without credentials |
| SSH `github.com:22` via CONNECT proxy | **Works**: GitHub banner. The host key is GitHub's published ED25519 key, `SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU`. "Permission denied (publickey)" until the deploy key is added |
| SSH `ssh.github.com:443` via CONNECT proxy | **Works**, same as above. **This is the chosen route** |
| HTTPS `github.com` | Works (anonymous `git ls-remote` and clone, public repo). It is used for fetch only |

- **Case: deploy key over SSH through the box proxy.** The token branch did not fire.
- **The key.** Keela generated an ed25519 pair on the box. The private half is
  `~/.ssh/grok_feed_deploy` (mode 600, outside any repo). The public half goes to Jeff:
  `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKffb3dIKcBL7ve5xgKfrhPQWy0rOYdRv9gnmsMeXXWA keela-box grok lane (assistant-usage deploy key)`
- **R5 (what Jeff does).** Add that key under the repo's Settings → Deploy keys → Add deploy key,
  titled `keela-box grok lane`, with "Allow write access" ticked. Also confirm the `main-protection`
  ruleset blocks force pushes and deletions (Budzilla reports that it does).
- **R1 step 1 (after the key is added).** One authenticated test: `git ls-remote` over SSH, then a push to a
  throwaway branch, then delete that branch.

## 9. Cutover (R3) and rollback

1. Merge the `collect.py` box-copy commit (Jeff's `inferred_zero` ruling point), then the runner PR.
2. Jeff adds the deploy key. Keela runs the authenticated test in R1 step 1.
3. Pause the AI sampler. Then enable the 30-minute wake. The two never run in the same window.
4. Pass: three consecutive wake commits on `main`, each append-only and each carrying a fresh `weekly`
   row. Fail: re-enable the AI sampler and disable the wake. Rollback is content-based, because the
   AI sampler re-sends the whole local file.
5. Cut the keep-alive to once a day (section 7.2), retire `push-grok.sh` and `wait-tracker.sh`, and publish the receipt.

## 10. Before / after

| Item | Before | After |
|---|---|---|
| What runs the feed | AI sampler wake, hourly | Thin AI wake every 30 min running `feed-run.sh` (W2) |
| Tracker restart and box checks | Hourly keep-alive AI wake | Inside `feed-run.sh` on every wake. Keep-alive once a day |
| Reading | Wait up to 7 min for the thawed loop | One reading under the poll lock (R8) |
| Push | GitHub connector, whole file, 1 MiB literal cap | `git push` from the transport clone over the deploy key, through the box proxy |
| Append-only | A habit | Enforced: byte-prefix, 0 deletions, trailing newline, blob identity, no-token guards |
| Line endings | CRLF (`csv.writer` default) | LF for new rows. Old rows untouched |
| `grok_bot` plan | `SuperGrok Heavy` default, `Ultra` only when a run passed it by hand | `Ultra` in the script |
| `weekly` plan | Tracker tier | Unchanged. The endpoint really says `SuperGrok Heavy` |
| Freshness alarm | AI decides each run | Budzilla's off-box weekly-row watch (2 h), plus the healthchecks feed check (30 min period, 90 min grace) |
| Data contract and dashboard | — | Unchanged (the `grok_bot` line only if the rule switches to B) |

## 11. Not verified

- Whether a second independent Grok login works (7.4).
- The exact hibernate rule. Fable rated the 24-hour wake test optional, and W2 doesn't depend on it.
- The healthchecks.io account settings, which only Jeff can see.
- Repo settings: deploy keys and the ruleset, which Budzilla reported.
