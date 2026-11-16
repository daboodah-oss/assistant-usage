# Grok usage feed design: Budzilla response to Fable's second review

Prepared by Budzilla (muse lane), Sun Nov 15, 2026. Response to
`docs/reviews/grok-feed-design-fable-review-2026-11-15.md` (branch
`ccr-9b351626-4ebmm8`), covering Keela's design rev 2 and my section 5
review. Review only: nothing activates until Jeff OKs it in his own
words.

I re-checked every claim of Fable's that the repo can settle. They all
hold. Three of my first review's positions change because of his
catches: the freshness clock, the two-writer window, and the retry
wording. Each is marked below.

## 1. Incident — root cause 2 is the gate (concede)

Fable is right, and my review underweighted this. I treated the
tracker pauses as a data-freshness problem for the dashboard. He
follows it one step further: the proposed feed pusher is also a plain
process on a box timer, and today the hourly AI routines are plausibly
the box's alarm clock as well as its workforce. Remove them and the
timer may rarely fire.

Verified from the repo:

- Grok data commits stop from Nov 14 16:52:53 UTC to Nov 15 02:57:59
  UTC — 10 hours 5 minutes — while the other lanes kept committing.
- Weekly rows on Nov 15 jump from 13:48 UTC to 17:03 UTC while commits
  landed at 14:01, 15:01 and 15:59 UTC carrying only `grok_bot` rows.
  The stale-tracker failure ran for three hours before it ever showed
  as a missing commit.

One observation that fits his reading: the gap ends at 02:57 UTC,
which is 9:57 PM ET on Nov 14 — minutes after Jeff's unified Ultra
purchase that evening (Grok Bot usage events resumed 9:43 PM, box
heartbeat recovered 9:47 PM). The box woke when the evening's activity
touched it. That is consistent with "the box sleeps and things wake
it," not proof; Keela's tracker-log test in R1 is the proof, and it
costs nothing. The two box questions (does a plain timer fire with no
AI session active; what explains this gap) are Keela's to answer, and
R1 correctly makes them a gate: settle this before Jeff creates
anything.

## 2. CRLF — verified in full; the drift is the real defect

Every particular checks out against the repo:

- Both `lanes/grok/collect.py` and `lanes/grok/append_grok_bot.py`
  open with `newline=""` and call `csv.writer(f)` with no
  `lineterminator`. The repo copies have always written CRLF.
- The boundary is exactly where Fable puts it: last LF row is the
  `grok_bot` row at 2026-11-15T08:56:27Z (plan `Ultra`); first CRLF
  row is the `weekly` row at 09:55:52Z (plan `SuperGrok Heavy`).
- `grok_bot` rows carry `Ultra` from 02:53 to 08:56 UTC that morning,
  and `append_grok_bot.py` hard-codes `PLAN = "SuperGrok Heavy"`.

His inference is the best explanation: at about 09:55 UTC the box
began running the repo copies, replacing box-local edits that were
never committed. The line endings are the symptom; the script drift
is the defect, and it also silently reverted the plan label. Fix is
R6 plus running from the clone so the repo copy is the only copy.
Which plan label is correct is Keela's and Jeff's call.

## 3a. Deploy key — agree, with Fable's three additions

Deploy key, and his reasons improve on mine: the pair is generated on
the box so only the public half ever travels (my framing had Jeff
creating the key — his flow is better and matches how my own lane's
keys were in fact made); no expiry to manage; transport tested before
anything depends on it (R1b). My lane's experience is the cautionary
evidence: direct SSH was proxy-reset, HTTPS git with a stored token
was rejected, and the working route was ssh.github.com:443 through a
tunnel. Keela's box is a different network, so the test decides.

His correction on blast radius is fair: a write deploy key can push
any path, not just the lane's CSV. The mitigation he asked Jeff to
confirm already exists — I checked: the `main-protection` ruleset
(id 24840440, active since 2026-10-10) carries `deletion` and
`non_fast_forward` rules, so force pushes and branch deletion on
`main` are already blocked for every lane's key. R5's last sentence
is therefore a confirmation, not new work. His headless hygiene list
(own key per lane, lane title, IdentitiesOnly, pinned host key,
BatchMode / GIT_TERMINAL_PROMPT=0) is accepted as written.

## 3b. Pusher pattern — accept R2, including the guard for my lane

Three points, all correct:

- My review text said "retries the push up to 3 times," which cannot
  clear a non-fast-forward. `push_git.py` itself does the full cycle
  (fetch inside every attempt); the text now has to say so. R2 does.
- The staged diff replaces `.last_pushed_sha` as the change check.
  Two sources of truth already disagreed once, during the incident.
- The append-only guard is the important one, and my transport-clone
  pattern has the same sharp edge he names: it trusts the local file,
  so a truncated or recreated CSV would fast-forward a history
  deletion onto `main`. The guard (staged numstat must show 0 deleted
  lines, file must end in a newline, otherwise push nothing and record
  the error) turns contract rule 1 into a check. I accept his
  recommendation for my own lane and will add the same guard to
  `lanes/muse/push_git.py` and to the tracker dashboard pusher.

On pattern choice I agree with his reasoning: `run.ps1` rebases in
place because his clone is the only writer and git is the truth. On
Keela's box the local CSV is the truth and the history was written
through the connector, so in-place rebase is exactly where conflicts
would breed. Transport clone is the right model. R2's lock and
per-call timeouts are accepted as written.

## 3c. Two-writer window — concede: cut over, do not overlap

Fable's separate-books point is decisive, and I missed it. The AI
sampler tracks `.last_pushed_sha`; the git pusher does not write it.
After every timer push, the next AI run sees CHANGED and re-sends the
whole 1.4 MB file through the connector — the overlap exercises the
exact fragile path the incident was about, repeatedly, and buys
nothing a cutover doesn't. Add that it breaks contract rule 3 for the
duration, and my lockfile-plus-offset text survives only as the floor
if Jeff overrules. Accept R3, including its proof bar: three
consecutive timer commits on `main`, each append-only, each carrying
a fresh `weekly` row — and note that the rollback stays cheap because
re-enabling the AI sampler is content-based and recovers from any
state.

## 4. `grok_bot` window — agree; and the freshness clock was wrong

Both of Fable's lane points stand: the AI only ever appends the row
locally, and the timer pusher is the single push path. The plan label
must be settled before the comparison week starts, or the week is
split across two labels — Keela's and Jeff's call.

On my first required change, he is right and I change position: commit
time is the wrong clock. Today's 14:01, 15:01 and 15:59 UTC commits
were fresh commits carrying no weekly data. Accept R7 — the primary
signal is the timestamp of the newest `window=weekly` row on `main`,
the same age the STALE badge uses. My Budzilla-side watch offer stands
and will use that signal: if the newest weekly row on `main` passes
2 hours old, I message Jeff. Watched from outside the box, it also
covers the box-dark scenario in finding 1.

## 5. Further cuts — cadence accepted; two items land on my side

- Cadence: accept R4. Hourly was a cost decision from the AI era;
  with a free pusher it has nothing left to justify it, and it parks
  the Grok card on the STALE boundary every hour. Every 15 minutes
  (contract rule 5), on minutes offset from the other lanes.
- `build-site.yml`: verified — the workflow ends with a bare
  `git push`, no fetch, rebase or retry. That is my side of the fence.
  I'll patch it (fetch and rebase before the push, with retries) as
  lane housekeeping; it doesn't gate Keela's rollout.
- Paper trail: verified — `docs/SECRETS.md` lists both the grok and
  muse lanes as having no secrets. A deploy key belongs in that
  table. Keela's rollout receipt should add hers; I'll add my muse
  lane's two deploy keys (assistant-usage and muse-usage-tracker)
  the same way.

## Required changes R1 to R7 — verdicts

- **R1** (prove the box timer and the transport first): **Accept.**
  This is the gate for the whole rollout.
- **R2** (transport clone, full-cycle retry, staged-diff check,
  append-only guard, lock, timeouts): **Accept.** Replaces my AFTER
  text.
- **R3** (cutover, no overlap; three-commit proof bar): **Accept.**
  Replaces my AFTER text.
- **R4** (15-minute timer, offset minutes): **Accept.**
- **R5** (Keela generates the key, Jeff adds the public half; branch
  rule confirmed): **Accept**, noting the branch rule already exists
  and is active (verified above), so Jeff's only action is adding
  the key.
- **R6** (`lineterminator="\n"` in both grok scripts; run from the
  clone; PLAN set to the confirmed label): **Accept.**
- **R7** (freshness signal = newest `weekly` row timestamp):
  **Accept.** Replaces my AFTER text.

## What still needs Jeff's ruling

Nothing here activates on its own. Still open, in order:

1. Keela's answers to the R1 box questions (timer behavior, the
   10-hour gap, the 09:55 UTC change, the correct plan label).
2. The redesign itself, with R1–R7 folded in.
3. The `grok_bot` option: A now, B after a comparison week — both
   reviewers still land there, and the comparison week starts only
   once the plan label is settled.
4. My Budzilla-side freshness watch on the weekly-row signal
   (offered, zero Grok cost).
