# Grok feed stalls, Nov 16 / Nov 20 / Nov 21: root cause and the fix that ends the pattern (pending Jeff review)

**Status: PENDING JEFF REVIEW. Nothing in section 5 is active.** This doc changes no script,
config or box file. Each change goes in only after Jeff approves it in his own words in chat, as a
separate `keela/` PR that changes exactly the lines shown.

Prepared by Keela, Sat Nov 21, 2026, about 6:45 PM ET. All times ET (UTC-5) unless marked UTC.
Sources: `/workspace/grok-feed/state/status.log` (256 runs, Nov 15 9:46 PM to Nov 21 6:15 PM),
`status.json`, `/workspace/ops/{bootstrap.log,heartbeat.log,reboots.log}`, and live probes at
6:31 PM ET. Earlier review: `docs/reviews/grok-feed-fix-https-lock-keela-2026-11-16.md`.

## 1. Plain terms

The feed has two separate weak points, and every stall this week was one or both of them:

1. **The push road is blocked.** The feed sends its rows to GitHub over SSH, which is tunnelled
   through the box's outbound proxy. Sometimes that proxy accepts the connection and then hangs
   up on it at once. While that lasts, every run reads Grok fine and saves the rows on the box,
   then can't deliver them. There is no second road, so it just keeps failing until the proxy
   starts passing SSH again on its own.
2. **A stuck lock (fixed this morning).** Only one feed run may go at a time. Until Sat 8:25 AM ET,
   a run that had to restart the box's heartbeat helper handed its "I'm running" lock to that
   helper, which lives for days. Every later wake then saw the lock, quietly skipped, and wrote
   nothing to the log. That was fixed (`8>&-`, approved 8:25 AM ET).

No readings were lost in either case: failed pushes keep every row in the local CSV. Skipped
runs (the lock case) took no reading at all, so those intervals have no rows.

## 2. Timeline (from status.log; push stats over all 256 runs: 220 ok first try, 5 ok on retry 2-3, 31 failed)

| Stall | When (ET) | What stopped | Class | Recovered |
|---|---|---|---|---|
| Mon Nov 16 | 1:46 PM | Box rebooted 1:45:52 PM. First run: reading ok, push fail (SSH closed by proxy) | SSH push block | - |
| | 1:46 PM to 5:10 PM (204 min, no logged runs) | Runs SKIPped silently: heartbeat/tracker restarted by a feed run inherited the lock (fd 8). Fixed by hand ~5:08 PM | Lock leak | 5:10 PM (runs resume) |
| | 5:10 PM Nov 16 to 2:42 AM Nov 17 (20 runs) | Reading ok every run, push fail every run | SSH push block | **3:08 AM Nov 17**, no reboot, no change on the box: proxy began passing SSH again |
| Fri Nov 20 | 8:44 PM | Box rebooted 8:43:59 PM (boot 8bf7b6b7). That run: reading ok, push fail | SSH push block (1 run) | - |
| | 8:44 PM Fri to 8:28 AM Sat (704 min, no logged runs) | The 8:44 PM run's bootstrap started the heartbeat (`heartbeat=started`, bootstrap.log 8:44:00 PM) while holding the lock; every later wake SKIPped without logging. **Not hibernation:** heartbeat.log has 67 pings in that window and the keep-alive ran hourly. | Lock leak | **8:28 AM Sat**, 3 min after the `8>&-` lock fix; SSH also worked again |
| Sat Nov 21 (today) | 3:06 PM to now (7 runs: 3:06, 3:46, 4:15, 4:44, 5:08, 5:40, 6:15 PM) | Reading ok every run, push fail every run. **No reboot** (last reboot Fri 8:43 PM) | SSH push block | Not yet. Re-probe 6:31 PM ET: proxy CONNECT ok, then `Connection closed by UNKNOWN port`; HTTPS to GitHub works |

Other single SSH failures that self-healed by the next run: Mon Nov 16 4:08 AM, Thu Nov 19 10:13 PM.
Retries that succeeded on attempt 2 or 3: Nov 16 8:41 AM, Nov 17 3:15 PM and 4:42 PM, Nov 19 2:15 AM,
Nov 21 11:15 AM.

**Does SSH recovery line up with anything?** No. Breaks: once right after a reboot (Nov 16), once
with no reboot (today). Recoveries: 3:08 AM Nov 17 with nothing changed on the box, and Sat
morning. Nothing on the box changes when it breaks or recovers, so the cause is in the egress
proxy's handling of SSH tunnels, outside our control. HTTPS through the same proxy has not failed
once in any of these windows.

**Hibernation:** no gap this week is explained by hibernation. The only gaps over 45 minutes
(204 min Nov 16 and 704 min Fri/Sat) are both lock-leak windows with the box awake.

## 3. Why the 30-minute wake doesn't prevent it

- The wake reruns the **same** script on the **same** road. Each run tries SSH 3 times, all
  through the same proxy, within about a minute. When the proxy is rejecting SSH, all 3 fail,
  and so does the next wake, and the one after. Retrying a blocked road doesn't unblock it.
- During the lock leak, the wake did start, but the run quit on its first line ("another run
  holds the lock") before writing anything. The wake could not see that the "other run" was
  really a long-lived helper.
- Nothing alerts on either case. `status.json` counts `consecutive_fail` (7 at 6:15 PM today) but
  nothing reads it. SKIPs are not written to `status.log` at all. The Healthchecks hook in
  `feed-run.sh` is unused: every run shows `hc=unset` (no `GROK_FEED_HC_URL`), so no outside
  service notices that pings stopped or failed.

## 4. Why it comes back after recovering

Recovery was never a fix. Both SSH recoveries happened because the proxy started passing SSH
again on its own; the feed still has only that one road, so the next time the proxy blocks SSH
(it has done so on 3 separate days this week, with and without a reboot), it stalls again. The
lock leak recurred Fri night for the same reason: it was diagnosed Nov 16 and the fix was
proposed, but the code wasn't changed until Sat 8:25 AM, so the Fri 8:43 PM reboot hit it again.
The lock leak is now fixed; the SSH dependency is not.

## 5. Proposed changes (each needs Jeff's own-words OK)

### Change 1 (ends the pattern): a second push road that does not use SSH

Exactly **Change 2 of `docs/reviews/grok-feed-fix-https-lock-keela-2026-11-16.md` section 3**
(BEFORE/AFTER of `lanes/grok/push_feed.py` is in that doc and is unchanged): push over SSH as
today; if SSH fails without a ref-level rejection and a token file exists with mode 600, push the
same commit over HTTPS with a fine-grained token read by a git credential helper (never in argv,
URL, config, log or commit; output redacted). Status shows `transport=ssh|https`.

**WHY:** HTTPS through the proxy has worked in every stall window, including now. With this,
the SSH block becomes a log detail instead of an outage. This matches Jeff's Nov 15 ruling
("Deploy key if SSH works, otherwise a fine-grained token over HTTPS").

**What Jeff does:** on GitHub, create a fine-grained personal access token: resource owner
`daboodah-oss`, repository access *only* `daboodah-oss/assistant-usage`, permission
*Contents: Read and write* (nothing else), expiry of his choice (90 days suggested). He enters
it through the masked in-chat form; Keela stores it at `~/.config/grok-feed/github_token`
(mode 600). It is never typed into chat, echoed or committed.

*Alternative with no new token:* the feed's wake routine could, when a run ends `PUSH fail`, push
the local CSV with the GitHub connector already used tonight (append-only, byte-prefix check
first, `data/grok/usage.csv` only). This changes the wake routine's saved prompt, so it also
needs Jeff's OK. It only works when the wake routine runs, so Change 1 is the better fix; this is
a fallback if Jeff prefers not to create a token.

### Change 2: log SKIPs and alert when the lock is stuck

**Location:** `lanes/grok/feed-run.sh`, line 85.

BEFORE:
```bash
flock -n 8 || { echo "GROK_FEED SKIP at=$(ts_et) reason=another_run_holds_lock"; exit 0; }
```
AFTER:
```bash
flock -n 8 || {
  line="GROK_FEED SKIP at=$(ts_et) reason=another_run_holds_lock holders=$(fuser "$STATE/feed.lock" 2>/dev/null | wc -w)"
  [ $DRY = 0 ] && echo "$line" >> "$STATE/status.log"
  age=$(( $(date +%s) - $(stat -c %Y "$STATE/status.json" 2>/dev/null || echo 0) ))
  [ "$age" -gt 3600 ] && echo "ALERT grok feed: no finished run for $((age/60)) min; lock held by another process"
  echo "$line"; exit 0; }
```
**WHY:** the two lock-leak stalls (204 min and 704 min) were invisible because SKIP wrote
nothing. A real overlapping run finishes in minutes; a lock held for over an hour is a leak.

### Change 3: alert after consecutive push failures

**Location:** `lanes/grok/feed-run.sh`, `finish()`, the two lines after the `status.json` update.

BEFORE:
```bash
  echo "$line"
  [ "$st" = FAIL ] && exit 1 || exit 0
```
AFTER:
```bash
  if [ $DRY = 0 ] && [ "$st" = FAIL ]; then
    n=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("consecutive_fail",0))' "$STATE/status.json" 2>/dev/null || echo 0)
    { [ "$n" = 2 ] || [ $(( n % 6 )) = 0 ]; } && echo "ALERT grok feed: $n failed runs in a row; rows are safe on the box but the site is not updating"
  fi
  echo "$line"
  [ "$st" = FAIL ] && exit 1 || exit 0
```
**WHY:** today's stall was known at 3:06 PM only because Keela read the run output; the feed
itself never raised it. Alert at the 2nd fail (about an hour), then every 6 (about 3 hours), so
no re-ping flood. Assumes the wake's saved prompt relays `ALERT` lines as it does for boxchrome;
if not, that prompt line is part of this change.

### Change 4: outside watchdog (Healthchecks)

Set `GROK_FEED_HC_URL` (already supported by `finish()`; currently unset) to a new Healthchecks
check, period 30 min, grace ~75 min. OK runs ping, FAIL runs ping `/fail`, and silence (SKIP,
box asleep, wake not firing) trips the grace timer. **What Jeff does:** create the check in his
Healthchecks account (or have Budzilla do it, as for the keep-alive) and give Keela the ping URL
through the masked form. **WHY:** the only alert that works even when nothing on the box runs.

`bash -n` passes on `feed-run.sh` with Changes 2 and 3 applied to a scratch copy (checked 6:45 PM ET).

## 6. Tonight's bridge (done, no code change)

At 6:32 PM ET Sat Nov 21, the 42 unpushed rows were pushed append-only to `main` with the GitHub
connector: commit `e09fba8b5553e21fcb68ad8ebb4cffaf2f891fa7`, message
`grok: sample 2026-11-21T23:14:41+00:00`, `data/grok/usage.csv` only, +42 / -0. Before: fresh
`origin/main` CSV (1,653,705 bytes) was a byte prefix of the local CSV (1,659,522 bytes). After:
`origin/main` CSV equals the local bytes (sha256 `c13ce3e9...064bc`). Newest row 6:14 PM ET.
Until Change 1 (or SSH recovers), each new wake will still end `PUSH fail` and keep its rows
locally; the weekly reset at 9:41 PM ET (2026-11-22T02:41:26Z) is safe on the box either way,
and the next successful push publishes all of them.

## 7. Rollback

Each change is a separate PR; revert with a normal revert commit (never force-push). Delete the
token file and revoke the token on GitHub to disable Change 1; the feed then fails closed with
rows kept locally, as today. No token, key, proxy address or credential is in this doc.
