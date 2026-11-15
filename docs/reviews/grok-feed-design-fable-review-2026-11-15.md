# Grok usage feed design: Fable second review

Prepared by Fable (claude lane), Sun Nov 15, 2026.  Second review of
`docs/reviews/grok-feed-design-keela-2026-11-15.md` (rev 2, branch
`keela/grok-feed-design-2026-11-15`) and of Budzilla's review
`docs/reviews/grok-feed-design-budzilla-review-2026-11-15.md` (branch
`budzilla/grok-feed-review-2026-11-15`).  Review only: nothing activates
until Jeff OKs it in his own words.

Checked against `main` at `e792ae2`.  I can see the repo, not Keela's box,
so anything about the box is marked as an inference or a question.

## Summary

The direction is right: plain script, git transport, no hourly AI.  Four
things need to change before rollout, in this order of importance:

1. The redesign does not address root cause 2.  If box processes pause
   when the box is idle, a plain box timer pauses too (finding 1).
2. The pusher needs an append-only guard and a full-cycle retry, and it
   should copy Budzilla's transport-clone pattern, not my `run.ps1`
   pattern (finding 3b).
3. The two-writer window should not exist.  Cut over, do not overlap
   (finding 3c).
4. Deploy key, yes, but generated on the box, and only after a transport
   test (finding 3a).

Required changes R1 to R7 are collected at the end as exact BEFORE and
AFTER text.

## 1. Incident

Root cause 1 (push) holds up and I have nothing to add to Budzilla's read.

Root cause 2 is the one the redesign leaves open, and neither document
follows it through.  Keela's own timeline says the tracker, a plain
background process, produced no readings from 1:04 to 1:58 PM and from
2:20 to 3:01 PM because "the tracker's 5-minute timer pauses while the box
is idle".  The proposed feed pusher is also a plain process on a box timer.
If idle pauses one, it pauses the other.  Today the hourly AI routines are
what wake the box, so they are doing two jobs: running the scripts, and
being the box's alarm clock.  The redesign removes the first job and, with
it, the second.  Worst case after cutover: the timer almost never fires and
the feed goes dark except when something else happens to wake the box.

Two data points from `main` that fit this and that Keela can explain from
the box:

- Grok data commits stop from Nov 14 16:52 UTC to Nov 15 02:57 UTC (about
  10 hours) while the other lanes kept committing.
- On Nov 15, weekly rows jump from 13:48 UTC to 17:03 UTC even though
  hourly commits landed at 14:01, 15:01 and 15:59 UTC.  Those runs carried
  only `grok_bot` rows.  The stale-tracker failure was already happening
  for three hours before the incident window; it just did not show as a
  missing commit.

This has to be settled before Jeff creates anything (R1).  The existing
tracker log can probably settle it at zero cost: look for the longest run
of consecutive 5-minute readings that has no AI run inside it.

If the box does sleep, the options are: a free external waker for the box,
if the platform has one; moving the tracker and pusher to a machine that is
always on (the Grok login rotates on every use, so it must live in exactly
one place); or keeping one small AI wake whose only job is to wake the box.
That is a design decision for Keela and Jeff, and it changes the usage
savings, so it should be known before the OK, not discovered after.

## 2. CRLF

Budzilla's suspect is right, and the repo shows why it started when it did.

- Both repo scripts, `lanes/grok/collect.py` and
  `lanes/grok/append_grok_bot.py`, open with `newline=""` and call
  `csv.writer(f)` with no `lineterminator`.  Python's default is `\r\n`,
  so the repo copies always write CRLF.
- Yet 10,865 lines on `main` are LF.  So until this morning the box was
  running scripts that differ from the repo copies.
- The switch happens at one row boundary: the last LF row is the
  `grok_bot` row at 08:56:27 UTC, the first CRLF row is the `weekly` row
  at 09:55:52 UTC, and all 27 lines since are CRLF.
- At that same boundary the `grok_bot` plan label changes from `Ultra`
  (rows from Nov 15 02:53 to 08:56 UTC) back to `SuperGrok Heavy`.  The
  repo copy of `append_grok_bot.py` hard-codes
  `PLAN = "SuperGrok Heavy"`.

Inference: at about 4:55 AM ET the box began running the repo copies of
both scripts (a re-clone, a restore, or a bootstrap step), replacing
box-local edits that had never been committed.  The CRLF is the visible
symptom.  The underlying problem is that the box scripts and the repo
scripts had drifted, and the revert also undid the `Ultra` label.  Which
label is correct is Keela's and Jeff's call; the `weekly` rows have said
`SuperGrok Heavy` throughout.

Agree with Budzilla: leave existing rows alone, fix the writers (R6).  The
redesign should also close the drift itself: the timer runs the scripts
from the clone, so the repo copy is the only copy.

## 3. Redesign

### 3a. Deploy key vs fine-grained token

Deploy key.  Budzilla's reasons are right.  Three more from running a
headless lane:

- **The secret never has to move.**  With a deploy key, the key pair is
  generated on the box and only the public half goes to Jeff.  A public
  key is safe to paste in chat.  With a token, Jeff creates the secret in
  GitHub and it then has to travel to the box, and Keela's document rules
  out chat without naming another route.  This alone decides it.
- **No expiry.**  My lane's login has a fixed lifetime of about four
  weeks, and `run.ps1` carries roughly 20 lines of warning logic plus a
  popup because of it.  Fine-grained tokens expire by default.  Do not
  take on an expiry when a credential without one is available.
- **Transport is not a given.**  A deploy key is SSH only.  Budzilla's own
  lane found that their VM's proxy resets direct SSH, and
  `lanes/muse/push_git.py` reaches `ssh.github.com:443` through an HTTP
  CONNECT tunnel (`lanes/muse/ssh_proxy.py`).  It also records that HTTPS
  git with a stored token did not work there.  Keela's box may sit behind
  the same kind of proxy.  Test first (R1).  If SSH cannot leave the box
  even through the tunnel, a fine-grained token over HTTPS is the
  fallback, and then the transfer route and an expiry reminder both need
  an answer.

One correction to "grants push to this repo only, acceptable".  True, but
a write deploy key is not limited to Grok's file.  It can push any path,
including `site/build.py`, the other lanes' CSVs and
`.github/workflows/`, and it can force-push or delete `main` unless a
branch rule stops it.  A fine-grained token with Contents write alone
cannot change workflow files, so on that one point the token is narrower.
The cheap fix is a rule on `main` that blocks force pushes and deletions.
That protects the append-only history from every lane's key, including
the Muse key already in use.  I cannot see the repo settings from here, so
this is a check for Jeff, not a claim that it is missing (R5).

Headless hygiene for whichever key: its own key (never a copy of the Muse
key), titled by lane so it can be revoked alone; `IdentitiesOnly=yes`; the
GitHub host key pinned in `known_hosts` ahead of time so the first run
does not stop at a prompt; `BatchMode=yes` and `GIT_TERMINAL_PROMPT=0` so
a credential problem fails fast instead of hanging the timer forever.

### 3b. Fetch, rebase and retry: compared with `run.ps1`

What `run.ps1` does, and why each part is there:

1. `pull --rebase` **before** collecting, so the append lands on fresh
   `main`.  On failure: `rebase --abort`, log, carry on.
2. `git add -- <csv>` and `git commit -- <csv>`: only the one file can
   ever be committed, whatever else is lying in the folder.
3. The change check is git itself (`diff --cached --quiet`).  No side
   file.
4. Three attempts, and each failed attempt does a fresh `pull --rebase`
   before the next push, with a growing pause.
5. Push `HEAD:main`, never forced.  On final failure the commit stays
   local and the next run retries.
6. Always exit 0, one log line per step.

Against that, three gaps in the design as amended by Budzilla:

- **The retry is not a full cycle.**  Budzilla's text says fetch and
  rebase before pushing, then "retries the push up to 3 times on a
  non-fast-forward rejection".  Retrying only the push cannot succeed: a
  non-fast-forward stays one until you fetch again.  The fetch has to be
  inside the loop.  (`push_git.py` does this correctly; the review text
  does not say it.)
- **Two change checks.**  Keela's pusher runs `push-grok.sh` and commits
  "if CHANGED", which compares against `.last_pushed_sha`.  With git as
  the transport that side file is a second source of truth, and the
  incident already showed the two disagreeing.  Use the staged diff and
  retire the sha file for this path.
- **Nothing enforces append-only.**  This is the important one.  See
  below.

Which pattern fits Keela's box?  Not mine.  `run.ps1` works in place
because my clone is the only writer and the truth lives in git.  On
Keela's box the truth is the local CSV, the folder may not be a clean
clone at all (it has been pushed through the connector, not git), and the
rollback path writes `main` outside local git.  Rebase in place breaks
there: if the connector has already committed rows R1 and the local commit
adds R1 plus R2 at the same spot, the rebase conflicts.  Budzilla's
transport-clone pattern (`push_git.py`: fetch, reset the clone to
`origin/main`, copy the CSV in, commit, push) is content-based and has no
such conflict, so it is the right model.

But copy-in has one sharp edge that `push_git.py` also has today: it
trusts the local file completely.  If the local CSV is ever shorter or
different (box rebuilt, workspace restored from an older state, file
recreated by `collect.py`, which writes a fresh header when the file is
missing), the pusher will commit the deletion of history to `main` in a
perfectly ordinary fast-forward push.  The guard is one command: after
staging, `git diff --cached --numstat -- data/grok/usage.csv` must report
0 deleted lines, and the file must end in a newline.  Otherwise unstage,
write the error to the status file, push nothing.  That turns contract
rule 1 from a habit into a check (R2).  I recommend Budzilla add the same
guard to `push_git.py`; that is their lane and not part of this change.

Also in R2: one non-blocking lock around the whole run so a hung push
cannot stack runs, and a timeout on every git call.

### 3c. The two-writer window

Remove it.  Budzilla's lockfile and minute offset stop the two writers
from interleaving on the local CSV, but they do not cover the rest:

- It breaks contract rule 3, "one writer per file", for no gain that a
  cutover does not also give.
- The two writers keep separate books.  The AI sampler tracks
  `.last_pushed_sha`; the git pusher does not write it.  After every
  timer push the next AI run sees CHANGED and re-sends the whole 1.4 MB
  file through the connector, which is the exact fragile path the
  incident was about, exercised for nothing.
- If the pusher were built in place with rebase, the overlap is where it
  would hit the conflict described in 3b.
- "I confirm commits from both" does not test anything the cutover does
  not.  What needs proving is that the timer pushes on its own.

A cutover is safe because the rollback is content-based: re-enabling the
AI sampler sends the whole current file and recovers from any state.  The
cost of a failed cutover is a STALE badge for an hour or so, which the
dashboard labels honestly (R3).

If Jeff prefers the overlap anyway, Budzilla's AFTER text is the minimum,
and the transport-clone pattern becomes mandatory, not just recommended.

## 4. The `grok_bot` window

Within my lane, two points only:

- Whatever option Jeff picks, the AI should only ever **append** the row
  to the local CSV.  The timer pusher is the single push path.  That
  keeps one writer on `main`.
- The plan label on `grok_bot` rows regressed from `Ultra` to
  `SuperGrok Heavy` at 09:55 UTC today (finding 2).  Decide which is
  right before the comparison week starts, so the week is not split
  across two labels.

On Budzilla's first required change (freshness signal): right idea,
wrong clock.  Commit time can look fresh while no weekly data is
arriving.  It did today: commits landed at 14:01, 15:01 and 15:59 UTC
carrying only `grok_bot` rows.  Watch the timestamp of the newest
`window=weekly` row, which is the same age the STALE badge already uses
(R7).

## 5. Further cuts, and what both reviews missed

- **Cadence.**  Hourly was a cost decision.  Once the pusher is free
  there is no reason to keep it.  Contract rule 5 says every 15 minutes,
  and `site/build.py` marks a card STALE when the newest sample is over
  1 hour old, so an hourly timer puts the Grok card on the STALE line
  every single hour.  Run the timer every 15 minutes (R4), on minutes
  that do not coincide with the other lanes.
- **Box idle** (finding 1).  The largest open question.
- **Script drift** (finding 2).  Run from the clone.
- **Append-only guard** (finding 3b).
- **Wrong freshness clock** (finding 4).
- **Not blocking, Budzilla's lane:** `build-site.yml` ends with a bare
  `git push`.  If any lane pushes during the build, that push is rejected
  and the page misses that update until the next data push.  A third git
  pusher at 15 minutes makes this a little more likely.  A fetch and
  rebase before that push, with a couple of retries, would close it.
- **Paper trail:** `docs/SECRETS.md` says the grok lane has no secrets.
  A deploy key is one.  The change receipt in rollout step 4 should add
  it there (what it is, where it lives, how to revoke it), and the same
  for the Muse key.

## Required changes (exact text)

All BEFORE text is from Keela's document unless marked.

### R1. Section 4, step 1: prove the box and the transport first

BEFORE:

> 1. You create the repo-scoped key. I install it and test one push.

AFTER:

> 0. Before Jeff does anything, I prove two things and report both.
>    (a) A plain box timer keeps firing with no AI session active: either
>    the existing tracker log shows at least 2 hours of unbroken 5-minute
>    readings with no AI run inside that span, or a heartbeat timer shows
>    the same.  If it does not, the design stops here and comes back with
>    a plan for what wakes the box.
>    (b) Which git transport leaves the box: SSH on port 22, SSH to
>    `ssh.github.com` on port 443, or neither.
> 1. I generate an ed25519 key pair on the box and send Jeff only the
>    public half.  Jeff adds it as a deploy key (see "What Jeff would need
>    to do").  I test one push to a throwaway branch, not `main`, and
>    delete that branch.

### R2. Section 2, Feed pusher row (replaces Budzilla's AFTER text)

BEFORE:

> If CHANGED, it commits `data/grok/usage.csv` with `git` over a **repo-scoped key** (a GitHub deploy key or fine-grained token limited to `daboodah-oss/assistant-usage`, contents write only). No size limit, no AI.

AFTER:

> It pushes through a separate transport clone, the way
> `lanes/muse/push_git.py` does: the local CSV stays the source of truth.
> Each of up to 3 attempts is a full cycle: fetch `origin/main`, reset the
> clone to it, copy the CSV in, stage only `data/grok/usage.csv`, commit,
> push to `main`.  Never a force push.  The staged diff is the only change
> check; `push-grok.sh` and `.last_pushed_sha` are not used.  Before
> committing it requires the staged diff to be append-only (0 deleted
> lines) and the file to end in a newline; otherwise it pushes nothing and
> records the error.  Auth is a repo-scoped deploy key with write access.
> Every git call is non-interactive with a timeout, and the whole run
> holds a non-blocking lock so runs cannot overlap.  On final failure the
> rows stay in the local CSV and the next run retries.  No size limit, no
> AI.

### R3. Section 4, step 2 (replaces Budzilla's AFTER text)

BEFORE:

> 2. I add the plain timer. It runs side by side with the AI sampler for 2 hours, and I confirm commits from both.

AFTER:

> 2. I pause the AI sampler first, then enable the plain timer.  The two
>    never run in the same window.  I confirm three consecutive timer
>    commits on `main`, each append-only and each carrying a fresh
>    `weekly` row.  If any of the three fails, I disable the timer and
>    re-enable the AI sampler.

### R4. Section 2, Feed pusher row, and Section 3, Sampler schedule row

BEFORE (Section 2):

> Plain script on a box timer, e.g. hourly

AFTER:

> Plain script on a box timer, every 15 minutes (contract rule 5), on
> minutes offset from the other lanes

BEFORE (Section 3):

> Plain box timer every hour; AI routine deleted or paused

AFTER:

> Plain box timer every 15 minutes; AI routine deleted or paused

### R5. Section 2, "What Jeff would need to do"

BEFORE:

> Create one GitHub fine-grained token, or approve a deploy key, limited to `daboodah-oss/assistant-usage` with Contents read/write. I'll give step-by-step clicks. It gets stored on my computer only (file mode 600) and never goes in the repo or chat.

AFTER:

> Add one deploy key.  I generate the key pair on my computer and send
> only the public half, which is safe to paste in chat.  Jeff adds it
> under the repo's Settings, Deploy keys, titled `keela-box grok lane`,
> with "Allow write access" ticked.  I'll give step-by-step clicks.  The
> private half never leaves my computer (file mode 600) and never goes in
> the repo or chat.  Jeff also confirms that `main` has a rule blocking
> force pushes and deletions, or adds one.

### R6. `lanes/grok/collect.py` and `lanes/grok/append_grok_bot.py`

BEFORE (the append block in each file):

```python
        w = csv.writer(f)
```

AFTER:

```python
        w = csv.writer(f, lineterminator="\n")
```

Existing rows stay as they are.  The timer runs both scripts from the
clone, so the repo copy is the only copy.  `PLAN` in
`append_grok_bot.py` is set to whichever label Keela and Jeff confirm.

### R7. Section 2, Freshness check row (amends Budzilla's AFTER text)

BEFORE (Budzilla's AFTER):

> Reads the time of the newest `data/grok/usage.csv` commit on main as the primary signal; the box status file is supporting detail only.

AFTER:

> Reads the timestamp of the newest `window=weekly` row in
> `data/grok/usage.csv` on main as the primary signal, the same age the
> dashboard's STALE badge uses; the box status file is supporting detail
> only.

## What I did not verify

- Anything on Keela's box: whether the folder is a git clone, what wakes
  the box, which scripts it runs, its network egress.
- The repo's branch rules, deploy keys and Actions secrets.
- Script history before Nov 12: my clone is shallow.  The line-ending and
  plan-label evidence in finding 2 comes from the data file and the
  current repo copies of the scripts.
