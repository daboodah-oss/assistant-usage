#!/usr/bin/env bash
# Offline checks for the Healthchecks URL fallback and the retired SSH setup.
# Uses a localhost sentinel, never a real ping URL or token. Prints no URL.
#   bash lanes/grok/test_hc_url.sh
set -uo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
SCRIPT=$ROOT/lanes/grok/feed-run.sh
HC=/workspace/grok-feed/state/.hc_ping_url
FILE_URL=http://127.0.0.1:9/hc-file-sentinel
ENV_URL=http://127.0.0.1:9/hc-env-sentinel
TMP=$(mktemp -d /tmp/grok-hc-test.XXXXXX)
FAKEBIN=$TMP/bin
CURL_URL_FILE=$TMP/curl-url
GIT_LOG=$TMP/git.log

# The helper's path is the box state file. Record what was already there before
# creating it, and delete the directory only when this test created it.
hc_existed=0
dir_existed=0
saved_hc=""
[ -d /workspace/grok-feed ] && dir_existed=1
if [ -e "$HC" ]; then
  hc_existed=1
  saved_hc=$TMP/hc.saved
  cp -a "$HC" "$saved_hc"
fi
mkdir -p "$FAKEBIN" "$(dirname "$HC")" "$TMP/clone/.git" "$TMP/state"
printf 'timestamp_utc,usage_pct\n' > "$TMP/usage.csv"
touch "$TMP/reexec-marker"

cleanup() {
  if [ "$hc_existed" -eq 1 ] && [ -n "$saved_hc" ] && [ -f "$saved_hc" ]; then
    mkdir -p "$(dirname "$HC")"
    cp -a "$saved_hc" "$HC"
  else
    rm -f "$HC"
  fi
  if [ "$dir_existed" -eq 0 ]; then
    rm -rf /workspace/grok-feed
  fi
  rm -rf "$TMP"
}
trap cleanup EXIT

cat > "$FAKEBIN/git" << 'EOF'
#!/bin/bash
printf '%s\n' "$*" >> "${GIT_LOG:?}"
if [ "${1:-}" = "-C" ]; then shift 2; fi
case "${1:-}" in
  fetch|clone|ls-remote) exit 1 ;;
  *) exit 0 ;;
esac
EOF
cat > "$FAKEBIN/curl" << 'EOF'
#!/bin/bash
# Record the last argument (the ping URL). Print nothing.
printf '%s' "${@: -1}" > "${CURL_URL_FILE:?}"
exit 22
EOF
chmod 700 "$FAKEBIN/git" "$FAKEBIN/curl"

fail() { echo "FAIL: $1"; exit 1; }
ok() { echo "ok: $1"; }

# The real helper, extracted so trailing-whitespace cases do not need a full run.
awk '/^hc_ping_url\(\)/,/^}$/' "$SCRIPT" > "$TMP/hc_fn.sh"
# shellcheck disable=SC1091
source "$TMP/hc_fn.sh"

url_is() { # $1=got $2=want $3=label
  if [ "$1" = "$2" ]; then ok "$3"; else fail "$3 mismatch"; fi
}
leaks() { # $1=label, remaining args are files
  local label=$1 f
  shift
  for f in "$@"; do
    if [ -f "$f" ] && grep -F -q -e "$FILE_URL" -e "$ENV_URL" "$f"; then
      fail "$label leaked a ping URL"
    fi
  done
}

# Function: file fallback strips trailing whitespace and ignores later lines.
unset GROK_FEED_HC_URL
printf '%s   \nsecond-line\n' "$FILE_URL" > "$HC"
chmod 600 "$HC"
url_is "$(hc_ping_url)" "$FILE_URL" "file fallback strips trailing whitespace"

# Function: an empty env var falls through to the file; a non-empty one wins.
GROK_FEED_HC_URL=
got=$(hc_ping_url)
url_is "$got" "$FILE_URL" "empty env falls back to the file"
GROK_FEED_HC_URL=$ENV_URL
got=$(hc_ping_url)
url_is "$got" "$ENV_URL" "env var wins over the file"
unset GROK_FEED_HC_URL
unset got

# Function: missing file and a non-regular path yield an empty result.
rm -f "$HC"
url_is "$(hc_ping_url)" "" "missing file is unset"
mkdir -p "$HC"
url_is "$(hc_ping_url)" "" "non-regular path is unset"
rmdir "$HC"

run_feed() {
  : > "$CURL_URL_FILE"
  : > "$GIT_LOG"
  # shellcheck disable=SC2091
  out=$(env -u GROK_FEED_HC_URL -u GROK_FEED_GH_TOKEN \
    PATH="$FAKEBIN:$PATH" \
    GROK_FEED_REEXEC="$TMP/reexec-marker" \
    GROK_FEED_CLONE="$TMP/clone" \
    GROK_FEED_STATE="$TMP/state" \
    GROK_FEED_CSV="$TMP/usage.csv" \
    CURL_URL_FILE="$CURL_URL_FILE" \
    GIT_LOG="$GIT_LOG" \
    "$@" \
    bash "$SCRIPT" --no-reading --no-bootstrap 2>&1) && rc=0 || rc=$?
}

assert_no_leak() {
  leaks "stdout" <(printf '%s' "$out")
  leaks "status" "$TMP/state/status.log" "$TMP/state/status.json"
  if grep -F -q -e "$FILE_URL" -e "$ENV_URL" <<<"$out"; then
    fail "runner output leaked a ping URL"
  fi
}

assert_git_https_only() {
  if grep -F -q 'ssh.github.com' "$GIT_LOG"; then fail "git was pointed at ssh.github.com"; fi
  if grep -F -q 'core.sshCommand' "$GIT_LOG" && grep -F -q 'ProxyCommand' "$GIT_LOG"; then
    fail "sshCommand was configured"
  fi
  grep -F -q -- '--unset-all remote.origin.pushurl' "$GIT_LOG" || fail "pushurl was not cleared"
  grep -F -q -- '--unset-all core.sshCommand' "$GIT_LOG" || fail "sshCommand was not cleared"
  if grep -F -q 'ssh_proxy.py' "$GIT_LOG"; then fail "ssh_proxy.py was loaded"; fi
}

# Full run: file fallback, URL reaches curl only, fetch failure still clears SSH config.
printf '%s\n' "$FILE_URL" > "$HC"
chmod 600 "$HC"
run_feed
[ "$rc" -eq 1 ] || fail "file-fallback run exit $rc"
url_is "$(cat "$CURL_URL_FILE")" "$FILE_URL/fail" "file URL passed to curl on FAIL"
grep -F -q 'hc=err' <<<"$out" || fail "expected hc=err when the ping fails"
assert_no_leak
assert_git_https_only
ok "file fallback run hid the URL and cleared SSH config"

# Full run: env wins, and the file URL is not what curl receives.
printf '%s\n' "$FILE_URL" > "$HC"
run_feed GROK_FEED_HC_URL="$ENV_URL"
[ "$rc" -eq 1 ] || fail "env-url run exit $rc"
url_is "$(cat "$CURL_URL_FILE")" "$ENV_URL/fail" "env URL passed to curl"
assert_no_leak
ok "env URL preferred and hidden"

# Full run: nothing configured.
rm -f "$HC"
run_feed
[ "$rc" -eq 1 ] || fail "unset run exit $rc"
[ ! -s "$CURL_URL_FILE" ] || fail "curl ran with no ping URL configured"
grep -F -q 'hc=unset' <<<"$out" || fail "expected hc=unset"
assert_no_leak
assert_git_https_only
ok "unset URL skips the ping"

# Retired stub refuses to tunnel and prints no secret.
stub_err=$(python3 "$ROOT/lanes/grok/ssh_proxy.py" ssh.github.com 443 2>&1) && fail "stub exited 0" || true
grep -F -q 'retired 2026-11-26' <<<"$stub_err" || fail "stub did not say it is retired"
grep -F -q 'CONNECT' <<<"$stub_err" && fail "stub tried to speak CONNECT" || true
ok "ssh_proxy stub refuses to tunnel"

echo "all hc/ssh checks passed"
