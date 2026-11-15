# Grok usage feed design: Budzilla review of Keela's proposal

Prepared by Budzilla, Sun Nov 15, 2026. Review of
`docs/reviews/grok-feed-design-keela-2026-11-15.md` (rev 2, branch
`keela/grok-feed-design-2026-11-15`). Review only: nothing activates
until Jeff OKs it in his own words.

## 1. Incident

Both root causes hold up. I verified the timeline against the repo
directly: `3bd91cfa` (1:00 PM ET) was the last good commit, recovery
landed as `35ef3d27` (2:59 PM ET) and `cfce769c` (3:02 PM ET), and
the newest rows (weekly 7%, grok_bot 7.1%) match the report.

- Push: the 1 MiB cap being checked before `$file:` substitution is
  inside Keela's connector, which I can't inspect from my side, but
  the evidence fits it exactly — path-form pushes succeeded at
  ~1.46 MB at 1:00 and 2:59 PM while the 1:56 PM run failed on size —
  and the fix (snapshot file, exact `"$file:..."` argument, `--mark`
  only after a returned commit sha) targets the failure precisely.
- Tracker: readings do pause while the box is idle (visible in the
  commit cadence), and `collect.py`'s 20-minute freshness gate then
  honestly wrote no weekly rows from a 52-minute-old reading. The
  gate isn't a bug; the interaction is the cause.

The applied fixes are sufficient as an interim. Two misses:

- The alert policy. A first failure staying silent meant the only
  alarm for a two-hour outage was Jeff noticing the dashboard. The
  stale badge did its job, but "silent on first failure" should not
  apply to push failures — only to no-change runs.
- The leftover `.push_content.txt` (1.46 MB) should be deleted.

Structural note: the interim fix still depends on an AI formatting a
tool argument exactly right every hour. That is the fragility the
redesign removes — don't let the interim become permanent.

## 2. CRLF

The dashboard is safe. `site/build.py` reads with `open(newline="")`
plus `csv.DictReader`, which treats `\r\n` as the row terminator. I
confirmed the repo file's newest 27 lines are CRLF and the parsed
values (including the 3:01 PM rows) are correct; the `\r` never
reaches a field the dashboard uses, and the numeric columns are
mid-row anyway.

Leave the existing rows exactly as they are: the file is append-only,
and rewriting history to normalize endings would churn 1.4 MB and
break the sha bookkeeping for zero benefit.

Do fix the source on the feed side. Prime suspect: Python's
`csv.writer`, whose default line terminator is `\r\n` — check
`collect.py` and `append_grok_bot.py` for a writer missing
`lineterminator="\n"`. Both writers' rows turned at the same time
(~4:55 AM), which fits a shared edit or a shared helper.

## 3. Redesign

Sound, with three required changes (exact BEFORE/AFTER below).

Deploy key over a fine-grained token: a deploy key is scoped to this
one repo by design, has no expiry to lapse mid-automation, isn't tied
to Jeff's account, and revokes cleanly. Store the private key mode
600 on the box only, and set a lane commit identity ("Keela (grok
lane)") the way Fable's lane does.

Reliability: `main` also takes Muse and Claude lane commits, so the
pusher will occasionally hit a non-fast-forward rejection — it needs
fetch + rebase + retry, not a bare push.

Security: a write deploy key on that box grants push to this repo
only — acceptable, and strictly less access than the current
connector arrangement.

Required changes:

- Section 2, Freshness check row.
  BEFORE: "Reads the status file."
  AFTER: "Reads the time of the newest `data/grok/usage.csv` commit
  on main as the primary signal; the box status file is supporting
  detail only."
  (If the box dies, its status file dies with it; the commit clock
  is observable from outside the box.)

- Section 2, Feed pusher row.
  BEFORE: "If CHANGED, it commits `data/grok/usage.csv` with `git`
  over a repo-scoped key."
  AFTER: "If CHANGED, it commits `data/grok/usage.csv` with `git`
  over a repo-scoped deploy key; before pushing it fetches and
  rebases onto `origin/main`, and retries the push up to 3 times on
  a non-fast-forward rejection."

- Section 4, step 2.
  BEFORE: "It runs side by side with the AI sampler for 2 hours, and
  I confirm commits from both."
  AFTER: "It runs side by side with the AI sampler for 2 hours,
  offset to a different minute, and both writers take the same
  lockfile around collect + push so their runs can never interleave
  on the shared local CSV."

## 4. The `grok_bot` window

A now, B after the comparison week — endorsing Keela's
recommendation, with two refinements.

1. The comparison needs no new instrumentation: both series are
   already in the CSV (platform `grok_bot` rows and billing
   `weekly_GrokBot` rows), and since the Ultra switch they carry the
   same reset (both 2026-11-22T02:41Z in the newest rows). Today they
   tracked within rounding (platform 6.3 → 7.1 vs billing 6 → 7). A
   week of that is real evidence.
2. A has a display-side cost, and it's mine: the sub-block's stale
   threshold is the same 1 hour as the cards, so a daily row would
   show STALE ~23 hours a day. If Jeff picks A, I change the extra
   block's threshold to 26 hours — one line in `site/build.py`
   (`xs.age_h > 1` → `> 26`), my lane, no contract impact.

On B's status: not a schema change (same columns, same window name)
but a semantics change — `docs/DATA_CONTRACT.md` defines `grok_bot`
as the platform reading, so B needs a one-line contract amendment,
and the `raw` field must name the source (e.g.
`source=billing_product`) so old and new rows stay distinguishable
in history.

C is paying hourly AI rates for a number that moves slowly. No.

## 5. Further usage cuts

The daily AI freshness check can be deleted too. My Muse sampler
already runs every 15 minutes on my VM at zero Grok cost; I can
watch the grok lane's newest commit age from outside Keela's box and
alert Jeff if it passes 2 hours. That works even when her box is
fully asleep or dead — exactly when a box-side check is least
reliable. Needs Jeff's OK since it's my side, but it takes the
Grok-side AI wakes for this feed to zero.

Also: fold whatever pool checks remain in the hourly keep-alive into
that same arrangement or drop them, and land the redesign promptly —
the interim `wait-tracker.sh` adds up to 7 minutes to every hourly
AI run until then.

Agree on not trimming the per-product rows: with git transport,
delta compression makes the 1.4 MB file a non-issue.
