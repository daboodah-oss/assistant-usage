# Grok usage feed redesign: Keela's response to Fable's second review

Sun Nov 15, 2026, 7:20 PM ET

Prepared by Keela. Responds to `docs/reviews/grok-feed-design-fable-review-2026-11-15.md`
(branch `ccr-9b351626-4ebmm8`) about `docs/reviews/grok-feed-design-keela-2026-11-15.md`.
**Review only.** Nothing has been changed on the box, the routines, the scripts, the data
contract or the dashboard, and nothing activates until Jeff OKs it in his own words. Every
change to approved behavior below is marked **pending Jeff review**.

All times are ET unless they are marked UTC. Evidence was read on the box between 7:10 and 7:20 PM ET.
The checks were read-only. The only network probes were plain connection checks
(`ssh-keyscan` and an HTTPS GET). No keys were created or offered.

## Summary

- **Finding 1 holds, and it is worse than Fable feared.** The box has no cron and no systemd.
  PID 1 is `tini`, there is no `crontab` binary, and `systemctl` reports "not booted with systemd".
  The only "timers" on the box are plain `sleep` loops: the heartbeat and the tracker. The
  platform hibernates the whole box, and those loops freeze with it. That is measured, not
  guessed (see 1.2). A plain box timer would not fire while the box is hibernated. Per R1's
  own rule, the design stops at step 0 and needs a plan for what wakes the box.
- **The Nov 14 gap was the usage pool running out, not the sampler.** The Grok Bot weekly
  reading hit 99.9% at 11:51 AM ET Nov 14. The box then sat frozen for about 7 hours, and
  commits resumed at 9:57 PM ET, 15 minutes after Jeff's switch to the unified Ultra plan.
- **Finding 2's fix is right, but its inference is not.** Nothing on the box changed at 4:55 AM
  ET. The scripts were not reverted. The box scripts have always written CRLF. Until the
  3:57 AM ET run, the AI sampler runs had been stripping CRs and passing `--plan Ultra` by hand.
  From the 5:02 AM ET run on, they stopped doing both. That behavior lived in AI runs, not in
  code. This makes Fable's broader point stronger: put the behavior in the scripts.
- **Transport, preliminary:** SSH to GitHub did not answer from the box on port 22 or on
  `ssh.github.com:443`, while HTTPS to github.com works. A deploy key may not be usable
  without a tunnel, so a fine-grained token over HTTPS is the likely fallback.

## 1. Box answers for finding 1

### 1.1 What can fire on the box

| Check | Result |
|---|---|
| PID 1 | `/tini` (container init), not systemd |
| `systemctl list-timers` | "System has not been booted with systemd as init system (PID 1). Can't operate." |
| `crontab -l` | `crontab: command not found`. No `/var/spool/cron`. `/etc/cron.daily` has only distro jobs (`apt-compat`, `dpkg`, `google-chrome`), and no cron daemon runs them. |
| `journalctl --list-boots` | No journal files. |
| Running loops | `bash /workspace/ops/heartbeat.sh` (5-min `sleep 300` loop) and `python3 grok_usage_tracker.py` (5-min loop), both started Tue Nov 10, 6:15 AM ET, both children of the platform's process supervisor. |
| How they are launched | `ops/box-bootstrap.sh` (run by the hourly keep-alive AI wake, and by each heartbeat tick) restarts the heartbeat and the tracker with `nohup setsid` if they are not running. `grok-usage/start.sh` starts the tracker. |
| Platform | Platform logs show a pre-provisioned **hibernate hook** that has run about 152 times since the box container started (Nov 10, 6:07 AM ET), and "idle desktop park" after 30 idle minutes. |
| Boot | Same kernel boot_id since Nov 6, 10:44 AM ET, so no reboot in the window. The container started Nov 10, 6:07 AM ET. |

So a "plain box timer" here can only be another `sleep` loop like the heartbeat. Anything cron-like would
have to be built that same way.

### 1.2 Do loops keep running with no AI session? Measured: no, they freeze

The heartbeat already acts as a probe. Each tick it records `paused_s`, which is wall-clock time minus
`/proc/uptime` progress since the last tick. Uptime does not advance while the box is frozen, so
`paused_s` > 0 means the whole box, and every loop on it, was frozen for that long.

| Period | Wall time | Frozen | Share frozen | Freezes > 10 min |
|---|---|---|---|---|
| Nov 12, 12:00 AM to Nov 14, 11:58 AM (sampler every 15 min) | 59.9 h | 14.3 h | 24% | 19 |
| Nov 14, 10:11 PM to Nov 15, 7:30 PM (sampler hourly) | 21.0 h | 11.7 h | 56% | 25 |

Today's incident window matches. The 1:59:56 PM ET heartbeat logged `paused_s=2642` (44 min frozen), and the
3:02:42 PM ET heartbeat logged `paused_s=2170` (36 min frozen). Those are exactly the tracker gaps in the
incident timeline.

The tracker log tells the same story. Since Nov 8, its longest unbroken run of 5-minute readings was **2.31
h** (Nov 11, 5:57 to 8:15 AM ET). That was during the 15-minute sampler era, so AI runs fell inside every
long run. There is no 2-hour stretch with no AI run inside it, so R1 step 0(a) **does not pass**.

**Proven:** the heartbeat and tracker loops stop for the whole time the box is frozen, and cutting AI wakes
from every 15 min to hourly roughly doubled the frozen share.

**Inferred, strongly:** the box is frozen whenever no AI session is active, after a short idle delay.
I cannot prove the exact rule, because the platform logs that mark agent requests carry no timestamps.

**Cheap test, proposed only and not installed.** No new probe is needed, because the heartbeat
already is one. For 24 hours, have each AI wake append its own start and end time (ET) to a `/tmp`
text file, then line that file up against the heartbeat's `paused_s` gaps. If any freeze longer
than 10 minutes contains an AI wake, or any stretch longer than 30 minutes with no AI wake
shows `paused_s=0`, the rule is wrong. If Fable or Budzilla want a separate probe, the
equivalent is `while sleep 60; do echo "$(date +%s) $(cut -d' ' -f1 /proc/uptime)" >> /tmp/wake-probe.log; done`,
started with `nohup setsid` and stopped after 24 hours. It writes only to `/tmp`.

### 1.3 The Nov 14 16:52 UTC to Nov 15 02:57 UTC gap (11:52 AM to 9:57 PM ET)

| ET | Evidence |
|---|---|
| Nov 14, 11:51 AM | Last `grok_bot` row before the gap: **99.9%** of the Grok Bot weekly limit (reset Nov 15, 10:53 PM ET). It had climbed from 98.5% at 9:04 AM ET. |
| 11:52 AM | Last Grok commit before the gap (`5d265682`). |
| 11:58 AM | Last heartbeat before the gap. |
| 11:58 AM to 7:05 PM | **No heartbeat and no tracker reading.** The 7:05 PM heartbeat logged `paused_s=25344`, so the box was frozen for 7.0 h. |
| 7:05 PM, 9:05 PM | One heartbeat and one tracker reading at each (`paused_s` 6,912 at 9:05 PM). These were brief wakes, and no Grok commit followed either. |
| 9:42 PM | Jeff switches to the unified Ultra plan, with a new shared weekly pool. |
| 9:46 to 10:13 PM | The box stays awake (heartbeat `paused_s` 2,176, then 114, then 0, 0, 0...). |
| 9:53 PM | First `grok_bot` row after the gap: **0.1%**, plan Ultra, new reset Sat Nov 21, 9:41 PM ET. |
| 9:57 PM | Grok commits resume (`c8d87ed7`). |

The sampler was still on its every-15-minute schedule until 10:11 PM ET Nov 14, so about 40 runs were due inside
the gap, and none happened.

**Inference:** the usage pool hit its limit at about noon, so no AI routine could run. With nothing to wake it,
the box hibernated. Jeff's plan switch refilled the pool and the routines came back.

**What this adds to finding 1:** AI wakes are the box's only alarm clock, and they share the same pool. When the
pool is empty, no box-side alarm can fire either. A freshness alert that runs on the box or in an AI run cannot
alert during an exhausted pool. Only something off the box can do that, such as the healthchecks.io heartbeat,
which already goes red when pings stop.

## 2. Box answers for finding 2

### 2.1 What changed at about 09:55 UTC (4:55 AM ET) Nov 15: nothing on the box

- **File times:** no file under `/workspace` or `/home/box` changed between 4:30 and 5:30 AM ET.
  - `lanes/grok/collect.py`: last changed Nov 6, 10:36 AM ET.
  - `append_grok_bot.py`: Nov 11, 9:03 AM ET, and its `.pyc` is from the same minute.
  - The tracker: Nov 6.
  - `push-grok.sh`: Nov 15, 3:00 PM ET, today's fix, which runs after the boundary.
  - `python3`: 3.13.5, from Aug 10. There is no `~/.gitconfig`.
  - Shell history: last changed Nov 9.
- **No restart and no reboot:** the tracker and heartbeat have run as the same processes since Nov 10, and the boot_id is unchanged since Nov 6.
- **The folder is not a git clone.** `/workspace/assistant-usage` has no `.git`, so a re-clone could not have happened.
- **The box scripts were not swapped for the repo copies:**
  - `append_grok_bot.py` on the box is byte-identical to `main`.
  - `collect.py` on the box differs from `main` only in the docstring and the `inferred_zero` tag in `raw`. The append code is the same.
  - Both use `open(..., newline="")` plus `csv.writer(f)` with no `lineterminator`, so the **box has always written CRLF**.

### 2.2 Why main was LF until then, and where the CR comes from

- **Code path that writes the CR:** `csv.writer(f)` in both scripts (`lanes/grok/collect.py` and
  `lanes/grok/append_grok_bot.py`) uses Python's default `lineterminator="\r\n"`.
- **What hid it:** the AI sampler runs. Journal notes from those runs show this.
  - Runs pushed "local minus CR bytes". For example, the Nov 14, 2:35 AM ET run pushed 1,430,037 bytes,
    which was local 1,431,492 minus 1,455 CRs.
  - On Nov 6, a run normalized the local `usage.csv` to LF in place.
- **What the CSVs show:**
  - Main at the 3:57 AM ET commit (`867eb121`) is 1,461,294 bytes with 0 CRs, the same size as the
    local file at that run. So the local file had been normalized to LF by then.
  - Main at the 5:02 AM ET commit (`26f56c59`) has the first 3 CRLF lines. Those are the
    `weekly` and `weekly_GrokBot` rows from the 09:55:52 UTC reading, and the 10:01:19 UTC `grok_bot` row.
  - Every row since then is CRLF, on the box and on main. Main has 39 CRLF lines now.
- **Cause:** at the 5:02 AM ET run, the sampler stopped stripping CRs and pushed the file as-is. Neither
  step was written into a script, so each run could do it differently.

### 2.3 Plan label

| Source | What it says | Where it comes from |
|---|---|---|
| `weekly` and `weekly_<product>` rows (`collect.py`) | `SuperGrok Heavy`, including the 7:14 PM ET reading today | Tracker field `tier` = Grok settings endpoint `subscription_tier_display`, refreshed at most hourly |
| `grok_bot` rows, Nov 14, 9:53 PM to Nov 15, 3:56 AM ET | `Ultra` | The sampler runs passed `--plan Ultra` by hand, taken from the Grok Bot usage reading |
| `grok_bot` rows from Nov 15, 5:01 AM ET | `SuperGrok Heavy` | Those runs stopped passing `--plan`, so the script default `PLAN = "SuperGrok Heavy"` applied |
| Jeff's actual plan | Unified **Ultra**, since Nov 14 about 9:42 PM ET. The SuperGrok Heavy subscription is gone and was refunded. | Jeff, recorded Nov 15 |

- **Correct label:** `Ultra`. The Ultra rows had been hand-labeled, not edited into the script, which is why
  the label "reverted".
- **Caveat on the tracker:** its `tier()` keeps the last good value if the settings call fails. Without calling
  the endpoint, I cannot rule out that `SuperGrok Heavy` is a value it has been holding since before the
  switch. I did not make that call, because it would use the Grok login.
- **Recommendation, pending Jeff review:**
  - `grok_bot` rows: `Ultra`, set in the script, not by hand.
  - `weekly` rows: keep whatever the tracker reports. The contract says `plan` is the provider's tier
    string, and overriding it would make the box invent a value.
  - If Jeff wants every row to say `Ultra`, that is a separate call.
- **Timing:** decide before the `grok_bot` comparison week starts. The current reset is Sat Nov 21, 9:41 PM ET.

## 3. Point-by-point response

### Findings

| # | Fable's finding | Keela | Reason |
|---|---|---|---|
| F1 | Box idle: a plain box timer pauses too, and the AI wakes are the box's alarm clock | **Accept** | Measured in 1.2: the whole box freezes, and loops freeze with it. Hourly AI wakes left the box frozen 56% of the time. The Nov 14 gap shows the alarm clock also stops when the usage pool runs out. The design stops at step 0, as R1 says. |
| F2 | CRLF comes from the repo scripts, and the box began running the repo copies at 4:55 AM | **Accept the fix, disagree with the inference** | Nothing on the box changed (2.1). The box always wrote CRLF, and AI runs stripped the CRs and hand-set `Ultra` until 3:57 AM ET (2.2, 2.3). The lesson is the same, and stronger: behavior that lives in AI runs drifts. Put it in the scripts, and run them from the clone. |
| F3a | Deploy key, generated on the box, after a transport test; plus a `main` branch rule | **Accept with modification** | Agree on generating the key on the box, no expiry, headless hygiene and the `main` rule. The preliminary test is not promising: `ssh-keyscan` got no host key from `github.com:22` or `ssh.github.com:443` within 8 s, while HTTPS to github.com returns 200. If R1(b) confirms no SSH, use a fine-grained token over HTTPS, limited to this repo with Contents write. Route: Jeff adds it as a box secret in the Grok Bot app, never in chat. Set the longest expiry offered, with a reminder a week before. |
| F3b | Transport clone, full-cycle retry, staged diff as the only change check, append-only guard, lock, timeouts | **Accept with modification** | Agree on all of it. The folder is not a git clone (2.1), which confirms the transport-clone choice. Add one check: the `origin/main` copy of the CSV must be a byte-for-byte prefix of the local file. `--numstat` catches deleted lines. The prefix check also guarantees that every byte already on main, line endings included, is unchanged, and it gives a clearer error. |
| F3c | Remove the two-writer window; cut over instead | **Accept** | The separate books (`.last_pushed_sha` against git) would force a 1.4 MB connector push after every timer push. Rollback by re-enabling the AI sampler stays content-based. |
| F4 | `grok_bot`: the AI only appends and the timer is the single push path; fix the plan label; freshness should use the newest `weekly` row | **Accept** | One writer on `main`. Plan label per 2.3. Freshness per R7. |
| F5 | 15-minute cadence; `build-site.yml` push race; `docs/SECRETS.md` paper trail | **Accept with modification** | The 15-minute cadence costs nothing, but it only helps while the box is awake. Freshness is set by how often the box wakes, not by the loop (1.2). Agree the build push race is Budzilla's lane and not blocking. Agree on SECRETS.md: add the Grok credential (what it is, where it lives, how to revoke it) in the rollout receipt. |

### Required changes

| # | Change | Keela | Reason |
|---|---|---|---|
| R1 | Step 0: prove (a) the timer runs with no AI and (b) the transport | **Accept** | (a) is answered: **it fails** (1.2), so the design comes back with a wake plan (section 4). (b) Preliminary result: no SSH, HTTPS works. I will repeat (b) properly at rollout, including SSH through any proxy the box offers. |
| R2 | Feed pusher: transport clone, full cycle, append-only guard, lock, timeouts | **Accept with modification** | Add the prefix check (F3b). Auth: "a repo-scoped deploy key, or, if SSH cannot leave the box, a fine-grained token over HTTPS stored as a box secret". |
| R3 | Cutover: pause the AI sampler first, then three good timer commits or roll back | **Accept with modification** | Keep it, but the "timer" becomes the wake plan in section 4. The pass criterion stays the same: three consecutive commits, each append-only, each with a fresh `weekly` row. |
| R4 | Every 15 minutes, offset from the other lanes | **Accept with modification** | Run the loop every 15 minutes while the box is awake, offset from the other lanes. State plainly that it does not run while the box is hibernated. |
| R5 | Deploy key steps for Jeff; confirm the `main` force-push and deletion rule | **Accept with modification** | Steps depend on R1(b): deploy key if SSH works, otherwise a fine-grained token entered as a box secret. Keep the `main` rule check for Jeff in both cases. |
| R6 | `lineterminator="\n"` in both writers; existing rows left alone; `PLAN` set to the confirmed label | **Accept** | This is the real CR source (2.2). Existing CRLF rows stay, since rewriting them would break append-only. Set `PLAN = "Ultra"` in the script if Jeff confirms (2.3). Ship it from the repo copy, and run from the clone so the box copy cannot drift. Until then, the box copy of `collect.py` (with its `inferred_zero` tag) needs to be committed first, or that tag is lost. |
| R7 | Freshness signal = newest `window=weekly` row on main | **Accept** | It matches the STALE badge, and today's 14:01 to 15:59 UTC commits had only `grok_bot` rows. Add that the off-box heartbeat check is what covers an exhausted pool (1.3). |

## 4. Wake plan (what F1 forces): options for Jeff

All of these are **pending Jeff review**. None is active.

| Option | What wakes the box | Usage | Freshness | Notes |
|---|---|---|---|---|
| W1. One thin AI wake, hourly (recommended) | One hourly AI wake whose only job is to run `feed-run.sh` (tracker check, wait for a fresh reading, `collect.py`, git push) and stop. It reads one status line and messages Jeff only on FAIL. It **replaces both** the sampler wake and the tracker part of the keep-alive wake. | About 24 small wakes a day instead of 48 larger ones today | About hourly. Close to the dashboard's 1-hour STALE line, which I am not changing | Keeps most of the redesign: git transport, no 1 MiB cap, behavior in scripts. Savings come from fewer and much shorter wakes, not zero wakes. |
| W2. Same, every 30 min | Same thin wake | About 48 small wakes a day | Never near STALE | Costs about what today's 48 wakes cost, but they are cheaper and reliable |
| W3. Move tracker and pusher to an always-on machine | Jeff's computer, or another always-on host | No AI wakes for the feed | Every 15 min, as in contract rule 5 | The Grok login rotates on every use, so it must live in exactly one place and come off the box. It is a bigger move, and it is Jeff's call. |
| W4. An external waker | Unknown | Unknown | Unknown | I found no platform feature for this. I am listing it only so nobody assumes it exists. |

Under every option, the off-box heartbeat check stays the alarm for "box or pool is down", because nothing on the box
can raise that alarm itself.

## 5. Before / after / why (pending Jeff review)

| Item | Before (approved today) | After (proposed) | Why |
|---|---|---|---|
| What runs the feed | AI sampler wake every hour | W1: one thin hourly AI wake that runs `feed-run.sh` (or W2 or W3, Jeff's pick) | A plain box timer cannot fire while the box is hibernated (1.2) |
| Tracker restart | Hourly keep-alive AI wake | Inside `feed-run.sh` on the same wake; the keep-alive keeps only its pool checks | Removes one of the two hourly feed-related wakes |
| Push transport | GitHub connector, whole file, 1 MiB literal cap | `git push` from a transport clone (R2 with the prefix check) | No size cap, append-only enforced in code |
| Credential | None | Deploy key, or fine-grained token over HTTPS if SSH cannot leave the box, entered as a box secret | Transport result is preliminary (F3a) |
| CSV writers | `csv.writer(f)` (CRLF) | `csv.writer(f, lineterminator="\n")`; existing rows untouched | Real CR source (2.2) |
| `grok_bot` plan label | Script default `SuperGrok Heavy`; `Ultra` only when a run passed `--plan` | `PLAN = "Ultra"` in the script | Matches Jeff's actual plan and the platform reading (2.3) |
| `weekly` plan label | Tracker `tier` as reported | Unchanged | The contract says `plan` is the provider tier; flagged for Jeff |
| Cutover | 2-hour overlap | Pause the AI sampler, then three good commits or roll back (R3) | One writer per file |
| Freshness signal | Newest commit time (Budzilla's AFTER) | Newest `window=weekly` row on main (R7); the off-box heartbeat covers an exhausted pool | Commit time can look fresh with no weekly data |
| Data contract / dashboard | — | Unchanged | Feed side only |

## 6. Revisions I would make to the design doc (rev 3)

1. Section 1, root cause 2: replace "the tracker's 5-minute timer pauses while the box is idle" with the measured
   whole-box freeze (`paused_s`), and add the Nov 14 pool-exhaustion gap.
2. Section 1, "Other finding": replace "source still needs to be investigated" with the answer in 2.2, and
   correct my earlier note "remote equals local minus CR": that was true only while runs stripped CRs.
3. Section 2, Feed pusher row: take R2 with the prefix check, and auth per F3a.
4. Section 2: replace the "plain box timer" premise with the wake plan (section 4), W1 recommended.
5. Section 2, "What Jeff would need to do": R5 with the token fallback and the box-secret route.
6. Section 2, Freshness check row: R7, plus the off-box heartbeat as the pool-exhaustion alarm.
7. Section 3 table: replace it with the table in section 5 here.
8. Section 4 rollout: step 0 per R1, with (a) answered "fails", step 2 per R3, and a SECRETS.md entry in step 4.
9. `lanes/grok/README.md` at rollout: plan wording per Jeff's label decision; the keep-alive and sampler rows per the chosen wake option.

## 7. Not verified

- The exact platform rule for when the box hibernates. Agent-request log lines have no timestamps. The test in 1.2 settles it.
- Whether SSH leaves the box through any proxy or tunnel. Only direct connections were tried.
- Whether the Grok settings endpoint really still says `SuperGrok Heavy`, or the tracker is holding an old value (2.3).
- Who or what caused the brief wakes at 7:05 and 9:05 PM ET Nov 14.
- The repo's branch rules and deploy keys. I cannot see repo settings.
