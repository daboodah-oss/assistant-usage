#!/usr/bin/env bash
# feed-run.sh: one Grok usage feed run. The 30-minute AI wake runs this and stops (wake plan W2).
#
#   bash /workspace/assistant-usage-clone/lanes/grok/feed-run.sh \
#        [--grok-bot-pct P --grok-bot-reset ISO] [--dry-run] [--no-reading] [--no-bootstrap] [--setup]
#
# Steps: lock -> clone setup/fetch -> code from origin/main -> box bootstrap (heartbeat, tracker,
# boxchrome; replaces the keep-alive's tracker part) -> ONE tracker reading under the tracker's
# poll lock (R8) -> grok_bot row (PLAN Ultra, option A platform reading) + comparison pair ->
# collect.py weekly rows -> push_feed.py (byte-prefix + append-only guards; HTTPS with
# GROK_FEED_GH_TOKEN first, SSH deploy key as fallback, or SSH-only when the token is unset;
# full-cycle retry, never forced) -> status file (+ token-auth / token-expiry ALERTs) + optional
# healthchecks ping (R7).
# Nothing runs while the box is hibernated: the wake is the only clock.
# Idempotent: a re-run with nothing new appends nothing and pushes nothing. --dry-run writes to a
# scratch copy of the CSV and a scratch compare state, never pushes, never pings, skips bootstrap.
# Last line: GROK_FEED <OK|WARN|FAIL|SKIP|DRYRUN> key=value...; ALERT/ACTION lines above it.
# ALERT lines: boxchrome a->b; grok-feed push token auth failed/recovered (once per incident);
# grok-feed GROK_FEED_GH_TOKEN expires ... (once, 14 days ahead of GROK_FEED_TOKEN_EXPIRES_UTC).
# Exit 0 unless FAIL. Never prints secrets; never force-pushes; commits only data/grok/usage.csv.
set -uo pipefail

# Re-exec from a private copy so resetting the clone can never change this script mid-run.
if [ -z "${GROK_FEED_REEXEC:-}" ]; then
  tmp=$(mktemp /tmp/grok-feed-run.XXXXXX.sh) && cp "$0" "$tmp" && chmod 700 "$tmp" &&
    GROK_FEED_REEXEC="$tmp" exec bash "$tmp" "$@"
  echo "GROK_FEED FAIL reason=reexec_failed"; exit 1
fi
trap 'rm -f "$GROK_FEED_REEXEC"' EXIT

REPO_HTTPS=https://github.com/daboodah-oss/assistant-usage.git
REPO_SSH=ssh://git@ssh.github.com:443/daboodah-oss/assistant-usage.git
CLONE=${GROK_FEED_CLONE:-/workspace/assistant-usage-clone}
LANE_CSV=${GROK_FEED_CSV:-/workspace/assistant-usage/data/grok/usage.csv}
STATE=${GROK_FEED_STATE:-/workspace/grok-feed/state}
RUN=$STATE/run
CODE_REF=${GROK_FEED_CODE_REF:-origin/main}
KEY=${GROK_FEED_KEY:-$HOME/.ssh/grok_feed_deploy}
KNOWN=$HOME/.ssh/known_hosts_grokfeed
TRACKER_DIR=${GROK_TRACKER_DIR:-/workspace/grok-usage}
BOOTSTRAP=/workspace/ops/box-bootstrap.sh
CODE_FILES="collect.py append_grok_bot.py push_feed.py take_reading.py grokbot_compare.py ssh_proxy.py feed.conf"

DRY=0; READ=1; BOOT=1; SETUP_ONLY=0; GB_PCT=""; GB_RESET=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;; --no-reading) READ=0 ;; --no-bootstrap) BOOT=0 ;; --setup) SETUP_ONLY=1 ;;
    --grok-bot-pct) GB_PCT="${2:-}"; shift ;; --grok-bot-reset) GB_RESET="${2:-}"; shift ;;
    *) echo "GROK_FEED FAIL reason=unknown_arg:$1"; exit 1 ;;
  esac; shift
done
[ $DRY = 1 ] && BOOT=0
mkdir -p "$STATE" "$RUN"
ts_et() { TZ=America/New_York date +%Y-%m-%dT%H:%M:%S%z; }
T=() # status fields
add() { T+=("$1"); }

finish() { # $1=status
  local st=$1 line hc="skipped"
  local url="${GROK_FEED_HC_URL:-}"
  if [ $DRY = 0 ] && [ -n "$url" ]; then
    case "$st" in
      OK) curl -fsS -m 10 --retry 2 -o /dev/null --data-raw "grok-feed $st ${T[*]}" "$url" && hc=sent || hc=err ;;
      FAIL) curl -fsS -m 10 --retry 2 -o /dev/null --data-raw "grok-feed $st ${T[*]}" "$url/fail" && hc=sent_fail || hc=err ;;
      *) hc=none_for_$st ;;
    esac
  elif [ $DRY = 0 ]; then hc=unset; fi
  line="GROK_FEED $st at=$(ts_et) ${T[*]} hc=$hc"
  if [ $DRY = 0 ]; then
    echo "$line" >> "$STATE/status.log"; tail -n 3000 "$STATE/status.log" > "$STATE/status.log.tmp" && mv "$STATE/status.log.tmp" "$STATE/status.log"
    local tok=0; [ -n "${GROK_FEED_GH_TOKEN:-}" ] && tok=1   # presence only; the value is never read here
    python3 - "$STATE/status.json" "$st" "$line" "$tok" "${GROK_FEED_TOKEN_EXPIRES_UTC:-}" "$(ts_et)" <<'PY'
import json,sys,os,re,datetime as d
p,st,line,tok,exp,at=sys.argv[1:7]
try: s=json.load(open(p))
except Exception: s={}
nowd=d.datetime.now(d.timezone.utc); now=nowd.isoformat(timespec="seconds")
s.update(last_run_utc=now,last_status=st,last_line=line)
if st=="OK": s["last_ok_utc"]=now; s["consecutive_fail"]=0
if st=="FAIL": s["last_fail_utc"]=now; s["consecutive_fail"]=s.get("consecutive_fail",0)+1
# Push transport + token-auth alert (Option 3 Variant A, Jeff Nov 22 2026). One ALERT per incident
# plus one on recovery; the incident clears only when a push succeeds over HTTPS again.
m=re.search(r"push=\[(PUSH \S+)([^\]]*)\]",line)
if m:
    pv=re.search(r" via=(\w+)",m.group(2)); authf=" https_auth_fail=1" in m.group(2)
    if m.group(1).startswith("PUSH ok"):
        s["last_push_via"]=pv.group(1) if pv else "ssh"; s["last_push_ok_utc"]=now
    if authf:
        s["last_push_auth_fail"]=now
        if s.get("push_auth_state")!="fail":
            s["push_auth_state"]="fail"; s["push_auth_fail_since"]=now
            print("ALERT grok-feed push token auth failed (HTTPS 401/403) at %s; %s. Check GROK_FEED_GH_TOKEN "
                  "(expired, revoked or missing Contents: write); see docs/SECRETS.md" % (at,
                  "pushed via ssh_fallback" if m.group(1).startswith("PUSH ok") else "push FAILED, rows held locally"))
    elif m.group(1).startswith("PUSH ok") and pv and pv.group(1)=="https" and s.get("push_auth_state")=="fail":
        print("ALERT grok-feed push token auth recovered at %s (PUSH ok via=https; failing since %s)"
              % (at, s.get("push_auth_fail_since","?")))
        s["push_auth_state"]="ok"
# Token expiry: one ALERT once the documented expiry (feed.conf) is within 14 days.
if tok=="1" and exp:
    try:
        e=d.datetime.fromisoformat(exp.replace("Z","+00:00")); days=(e-nowd).total_seconds()/86400
        s["token_expires_utc"]=exp
        if days<=14 and s.get("token_expiry_alerted")!=exp:
            s["token_expiry_alerted"]=exp
            print("ALERT grok-feed GROK_FEED_GH_TOKEN expires %s (in %.1f days); renew it with the same scope and "
                  "update GROK_FEED_TOKEN_EXPIRES_UTC in lanes/grok/feed.conf" % (exp, max(days,0)))
    except ValueError: pass
json.dump(s,open(p+".tmp","w"),indent=1); os.replace(p+".tmp",p)
PY
  fi
  echo "$line"
  [ "$st" = FAIL ] && exit 1 || exit 0
}

# 1. one run at a time (non-blocking)
exec 8>"$STATE/feed.lock"
flock -n 8 || { echo "GROK_FEED SKIP at=$(ts_et) reason=another_run_holds_lock"; exit 0; }

# 2. transport clone (idempotent setup)
G() { timeout "${GT:-90}" env GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/bin/false git -C "$CLONE" "$@"; }
if [ ! -d "$CLONE/.git" ]; then
  timeout 300 env GIT_TERMINAL_PROMPT=0 git clone -q "$REPO_HTTPS" "$CLONE" || { add "step=clone"; finish FAIL; }
fi
G config remote.origin.url "$REPO_HTTPS"
G config remote.origin.pushurl "$REPO_SSH"   # SSH stays configured: fallback (token set) or only path (unset)
G config core.sshCommand "ssh -i $KEY -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$KNOWN -o ConnectTimeout=20 -o ServerAliveInterval=15 -o ProxyCommand='python3 $RUN/ssh_proxy.py %h %p'"
G config core.autocrlf false; G config core.safecrlf false
G config user.name "Keela (grok lane)"; G config user.email "grok-lane@keela-box.invalid"
G config push.default nothing

# 3. fetch and load this run's code from $CODE_REF (the repo copy is the only copy)
GT=120 G fetch -q origin main || { add "step=fetch"; finish FAIL; }
if [ "$CODE_REF" != origin/main ]; then
  b=${CODE_REF#origin/}; GT=120 G fetch -q origin "+refs/heads/$b:refs/remotes/origin/$b" || { add "step=fetch_code_ref"; finish FAIL; }
fi
if [ -n "${GROK_FEED_CODE_DIR:-}" ]; then   # testing only: load code from a working tree
  for f in $CODE_FILES; do cp "$GROK_FEED_CODE_DIR/$f" "$RUN/$f" || { add "step=load_code_dir"; finish FAIL; }; done
  add "code=dir:$GROK_FEED_CODE_DIR"
else
  for f in $CODE_FILES; do
    G show "$CODE_REF:lanes/grok/$f" > "$RUN/$f.tmp" 2>/dev/null && mv "$RUN/$f.tmp" "$RUN/$f" ||
      { rm -f "$RUN/$f.tmp"; add "step=load_code missing=lanes/grok/$f@$CODE_REF"; finish FAIL; }
  done
  add "code=$(G rev-parse --short "$CODE_REF")"
fi
GROK_BOT_SOURCE=platform; . "$RUN/feed.conf"
[ $SETUP_ONLY = 1 ] && { add "setup=done"; echo "GROK_FEED SETUP at=$(ts_et) ${T[*]}"; exit 0; }

# 4. box bootstrap: heartbeat, tracker restart, boxchrome (the keep-alive's checks, now free here)
chrome=unknown
if [ $BOOT = 1 ] && [ -f "$BOOTSTRAP" ]; then
  bl=$(timeout 60 bash "$BOOTSTRAP" 2>/dev/null 8>&- | tail -n1)
  chrome=$(sed -n 's/.*boxchrome=\([a-z]*\).*/\1/p' <<<"$bl"); tr_=$(sed -n 's/.* tracker=\([a-z]*\).*/\1/p' <<<"$bl")
  add "tracker=${tr_:-?} boxchrome=${chrome:-?}"
  lw=$(sed -n 's/.* lock_window=\([a-z]*\).*/\1/p' <<<"$bl"); [ "$lw" = no ] || lw=yes   # absent/odd -> yes (old behavior)
  prev=$(cat "$STATE/boxchrome.last" 2>/dev/null || echo unknown)
  # idle (Jeff, Nov 21 2026): inside the lock window idle counts as down; outside it, only up<->down alerts.
  if [ -n "$chrome" ] && [ "$prev" != unknown ] && [ "$prev" != "$chrome" ]; then
    if [ "$lw" = yes ]; then pn=${prev/idle/down}; cn=${chrome/idle/down}; else pn=$prev; cn=$chrome; fi
    if [ "$pn" != "$cn" ] && { [ "$lw" = yes ] || { [ "$prev" != idle ] && [ "$chrome" != idle ]; }; }; then
      echo "ALERT boxchrome $prev->$chrome at $(ts_et)"; fi
  fi
  [ -n "$chrome" ] && echo "$chrome" > "$STATE/boxchrome.last"
else
  pgrep -f grok_usage_tracker.py >/dev/null && add "tracker=running" || {
    add "tracker=not_running"; [ $DRY = 0 ] && setsid nohup bash "$TRACKER_DIR/start.sh" >/dev/null 2>&1 < /dev/null 8>&- & }
fi

# 5. one reading now (R8)
if [ $READ = 1 ]; then
  rl=$(timeout 600 python3 "$RUN/take_reading.py" --tracker-dir "$TRACKER_DIR")
  add "reading=$(awk '{print $2"/"$3}' <<<"$rl" | sed 's/mode=//')"
  echo "$rl" | grep -q 'mode=wait' && echo "NOTE one-shot reading unavailable (tracker lacks poll lock); waited for loop: $rl"
fi

# 6. working CSV (dry-run: scratch copy; the real lane CSV is never touched)
WORK=$LANE_CSV; CMPSTATE=$STATE/grokbot-compare
if [ $DRY = 1 ]; then
  mkdir -p "$STATE/dryrun"; cp "$LANE_CSV" "$STATE/dryrun/usage.csv"; WORK=$STATE/dryrun/usage.csv
  rm -rf "$STATE/dryrun/grokbot-compare"; [ -d "$CMPSTATE" ] && cp -r "$CMPSTATE" "$STATE/dryrun/"; CMPSTATE=$STATE/dryrun/grokbot-compare
fi
before=$(wc -l < "$WORK")

# 7. weekly rows (first: collect.py skips a reading older than the newest CSV row)
co=$(python3 "$RUN/collect.py" --out "$WORK" --log "$TRACKER_DIR/usage_log.jsonl")
case "$co" in *appended*) weekly=appended; add "weekly=$(sed -n 's/.*weekly=\([0-9.]*%\).*/\1/p' <<<"$co") plan=\"$(sed -n 's/.*plan=\(.*\))/\1/p' <<<"$co")\"";;
  *stale*) weekly=stale; add "weekly=stale";; *skip*) weekly=dup; add "weekly=already_have";; *) weekly=none; add "weekly=none";; esac
# 8. grok_bot row (PLAN Ultra)
if [ "$GROK_BOT_SOURCE" = billing ]; then
  gb=$(python3 - "$TRACKER_DIR/usage_log.jsonl" <<'PY'
import json,sys
for l in reversed(open(sys.argv[1]).read().splitlines()[-50:]):
    try: r=json.loads(l)
    except Exception: continue
    if r.get("ok"):
        v=(r.get("products") or {}).get("GrokBot")
        if isinstance(v,(int,float)) and r.get("period_end"): print(v, r["period_end"])
        break
PY
)
  if [ -n "$gb" ]; then
    out=$(python3 "$RUN/append_grok_bot.py" --pct "${gb% *}" --reset "${gb#* }" --source billing_product --out "$WORK"); add "grok_bot=billing:$(sed 's/ .*//;s/.*append: //' <<<"$out" | tr -d ' ')"
  else add "grok_bot=billing:absent"; fi
elif [ -n "$GB_PCT" ] && [ -n "$GB_RESET" ]; then
  out=$(python3 "$RUN/append_grok_bot.py" --pct "$GB_PCT" --reset "$GB_RESET" --out "$WORK")
  case "$out" in *"1 row"*) add "grok_bot=appended:$GB_PCT";; *) add "grok_bot=skipped";; esac
  cr=$(python3 "$RUN/grokbot_compare.py" --state-dir "$CMPSTATE" record --platform-pct "$GB_PCT" \
        --platform-ts "$(date -u +%Y-%m-%dT%H:%M:%S+00:00)" --tracker-log "$TRACKER_DIR/usage_log.jsonl")
  add "pair=$(sed 's/COMPARE record=//;s/ /,/g' <<<"$cr")"
else
  add "grok_bot=not_given"
fi

add "rows_added=$(( $(wc -l < "$WORK") - before ))"

# 9. comparison rule (prints COMPARE / ACTION lines)
python3 "$RUN/grokbot_compare.py" --state-dir "$CMPSTATE" evaluate | while read -r l; do
  case "$l" in ACTION*) echo "$l";; *) echo "$l" > "$STATE/.compare_last";; esac; done
add "compare=$(sed 's/COMPARE //;s/ /,/g' "$STATE/.compare_last" 2>/dev/null)"

# 10. push (R2)
if [ $DRY = 1 ]; then
  pl=$(timeout 900 python3 "$RUN/push_feed.py" --clone "$CLONE" --src "$WORK" --dry-run --probe-push); prc=$?
else
  pl=$(timeout 900 python3 "$RUN/push_feed.py" --clone "$CLONE" --src "$WORK"); prc=$?
fi
add "push=[$pl]"
if [ $prc -ne 0 ]; then finish FAIL; fi
[ $DRY = 1 ] && finish DRYRUN
case "$pl" in "PUSH ok"*|"PUSH noop"*) ;; *) finish FAIL;; esac
[ "$weekly" = appended ] && finish OK || finish WARN
