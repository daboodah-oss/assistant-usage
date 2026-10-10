#!/usr/bin/env python3
"""Claude lane sampler: append Claude subscription usage to data/claude/usage.csv.

Owner-hosted (docs/DEPLOYMENT.md pattern B).  Runs on the machine that holds
the Claude Code login, reads the same undocumented endpoint Claude Code's
/usage reads, and writes one row per window per run (docs/DATA_CONTRACT.md).
Stdlib only.  Works on Windows, macOS and Linux.

Principles:
  * Unknown is never zero.  Any failure or unrecognized shape writes NO row.
  * Expected failures exit 0.  A run that records nothing is not an error.
  * Tokens never leave this machine: never printed, never written to data/.

Credentials (checked in this order):
  1. CLAUDE_ACCESS_TOKEN / CLAUDE_REFRESH_TOKEN env vars (pattern A style).
     Rotated tokens go to CLAUDE_TOKEN_OUT as JSON (0600) if set.
  2. A Claude Code credentials file: CLAUDE_CREDENTIALS_FILE, else
     $CLAUDE_CONFIG_DIR/.credentials.json, else ~/.claude/.credentials.json.
     Rotated tokens are written back to that file under the same mkdir lock
     Claude Code uses (<dir>/.oauth_refresh.lock), so the login stays valid.

Other env vars:
  CLAUDE_PLAN         plan label override; otherwise taken from the
                      credentials file (subscriptionType / rateLimitTier)
  CLAUDE_NO_REFRESH   set to 1 to never refresh (read-only use of a login)
  CLAUDE_USAGE_CSV    output path override (default data/claude/usage.csv)
"""
import csv
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
TOKEN_URLS = (
    "https://platform.claude.com/v1/oauth/token",   # current endpoint
    "https://console.anthropic.com/v1/oauth/token",  # legacy fallback
)
# Public OAuth client id of the Claude Code CLI (not a secret).
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
USER_AGENT = "claude-code/2.0.0"
BETA = "oauth-2025-04-20"
HTTP_TIMEOUT = 30

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CSV_PATH = os.environ.get("CLAUDE_USAGE_CSV") or os.path.join(REPO, "data", "claude", "usage.csv")
LOCK_PATH = os.path.join(tempfile.gettempdir(), "assistant-usage-claude.lock")
LOCK_STALE_S = 120
REFRESH_LOCK_STALE_S = 60      # same as the CLI's .oauth_refresh.lock
REFRESH_LOCK_WAIT_S = 15
EXPIRY_SKEW_S = 120            # refresh this close to expiresAt instead of risking a 401
MIN_GAP_S = 120                # DATA_CONTRACT rule 6
HEADER = ["timestamp_utc", "usage_pct", "plan", "reset_iso", "window", "raw"]

_SECRETS = []  # token values to redact from any log line


def log(msg):
    for s in _SECRETS:
        if s:
            msg = msg.replace(s, "***")
    print(msg, file=sys.stderr)


def status_line(**kv):
    """Single machine/human readable result line on stdout (safe: no secrets)."""
    print("claude-collector: " + " ".join(f"{k}={v}" for k, v in kv.items()))


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def http(method, url, headers, data=None):
    """Return (status, parsed_json_or_None).  status 0 = network failure.

    Never follows redirects (a redirect from an auth host is treated as a
    failure so a bearer token is never replayed somewhere unexpected).
    """
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(req, timeout=HTTP_TIMEOUT) as r:
            status, body = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, body = e.code, e.read()
    except Exception as e:  # DNS, TLS, timeout
        log(f"http: {type(e).__name__} calling {urllib.parse.urlsplit(url).netloc}")
        return 0, None
    try:
        return status, json.loads(body.decode("utf-8", "replace"))
    except Exception:
        return status, None


def get_usage(access_token):
    return http("GET", USAGE_URL, {
        "Authorization": f"Bearer {access_token}",
        "anthropic-beta": BETA,
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })


def refresh_tokens(refresh_token):
    """One refresh attempt.  Returns the token response dict or None.

    Endpoint, form encoding and client id verified against community reports
    of the Claude Code CLI (platform.claude.com, falling back to
    console.anthropic.com only on 404/405/redirect/network failure; never on
    400/401/403/429, which retrying elsewhere cannot fix).
    """
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLIENT_ID,
    }).encode()
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    for url in TOKEN_URLS:
        status, js = http("POST", url, headers, body)
        host = urllib.parse.urlsplit(url).netloc
        if status == 200 and isinstance(js, dict) and isinstance(js.get("access_token"), str):
            return js
        log(f"refresh: {host} returned status {status}")
        if status in (0, 301, 302, 303, 307, 308, 404, 405):
            continue
        break
    return None


# --------------------------------------------------------------------------
# Credential sources
# --------------------------------------------------------------------------
class EnvCreds:
    """Tokens from env vars (pattern A style).  Rotation goes to CLAUDE_TOKEN_OUT."""

    def __init__(self, access, refresh, token_out):
        self.access, self.refresh, self.token_out = access, refresh, token_out
        self.plan = None

    def describe(self):
        return "env"

    def reload(self):
        return False  # nothing can change underneath us

    def save(self, tokens):
        new_refresh = tokens.get("refresh_token")
        out = {"access_token": tokens["access_token"],
               "refresh_token": new_refresh if isinstance(new_refresh, str) and new_refresh else self.refresh}
        if not self.token_out:
            log("warning: tokens rotated but CLAUDE_TOKEN_OUT unset; new refresh token is lost")
            return
        fd = os.open(self.token_out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(out, f)


class FileCreds:
    """Claude Code's .credentials.json.  Refresh under the CLI's own lock."""

    def __init__(self, path):
        self.path = path
        self.dir = os.path.dirname(path)
        self.lock_dir = os.path.join(self.dir, ".oauth_refresh.lock")
        self.data = None
        self.access = self.refresh = self.plan = None
        self.expires_at = None  # epoch seconds or None

    def describe(self):
        return "file"

    def reload(self):
        """Re-read the file.  Returns True if the access token changed."""
        old = self.access
        with open(self.path, encoding="utf-8") as f:
            self.data = json.load(f)
        oauth = self.data.get("claudeAiOauth") if isinstance(self.data, dict) else None
        if not isinstance(oauth, dict) or not isinstance(oauth.get("accessToken"), str):
            raise ValueError("credentials file has no claudeAiOauth.accessToken")
        self.access = oauth["accessToken"]
        self.refresh = oauth.get("refreshToken") if isinstance(oauth.get("refreshToken"), str) else ""
        exp = oauth.get("expiresAt")
        self.expires_at = exp / 1000.0 if isinstance(exp, (int, float)) and not isinstance(exp, bool) and exp > 1e11 else None
        sub = oauth.get("subscriptionType")
        tier = oauth.get("rateLimitTier")
        self.plan = sub if isinstance(sub, str) and sub.strip() else (tier if isinstance(tier, str) and tier.strip() else None)
        _SECRETS.extend([self.access, self.refresh])
        return old is not None and old != self.access

    def about_to_expire(self):
        return self.expires_at is not None and time.time() > self.expires_at - EXPIRY_SKEW_S

    def _acquire_lock(self):
        deadline = time.time() + REFRESH_LOCK_WAIT_S
        while True:
            try:
                os.mkdir(self.lock_dir)
                return True
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self.lock_dir) > REFRESH_LOCK_STALE_S:
                        os.rmdir(self.lock_dir)
                        continue
                except OSError:
                    pass
                if time.time() > deadline:
                    return False
                time.sleep(0.5)

    def _release_lock(self):
        try:
            os.rmdir(self.lock_dir)
        except OSError:
            pass

    def save(self, tokens):
        oauth = dict(self.data["claudeAiOauth"])
        oauth["accessToken"] = tokens["access_token"]
        new_refresh = tokens.get("refresh_token")
        if isinstance(new_refresh, str) and new_refresh:
            oauth["refreshToken"] = new_refresh
        ttl = tokens.get("expires_in")
        if isinstance(ttl, (int, float)) and not isinstance(ttl, bool) and ttl > 0:
            oauth["expiresAt"] = int((time.time() + ttl) * 1000)
        data = dict(self.data)
        data["claudeAiOauth"] = oauth
        tmp = self.path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self.path)
        self.data = data
        self.access, self.refresh = oauth["accessToken"], oauth.get("refreshToken", "")
        self.expires_at = oauth.get("expiresAt", 0) / 1000.0 if "expiresAt" in oauth else None

    def refresh_locked(self):
        """Refresh under the CLI lock.  Returns 'ok', 'reused', 'locked' or 'failed'.

        'reused': another process (usually Claude Code itself) refreshed
        between our read and our lock, so we just take its new token.
        """
        if not self._acquire_lock():
            return "locked"
        try:
            try:
                if self.reload():
                    return "reused"
            except Exception as e:
                log(f"re-read of credentials failed: {type(e).__name__}")
                return "failed"
            tokens = refresh_tokens(self.refresh)
            if not tokens:
                return "failed"
            _SECRETS.extend([tokens.get("access_token", ""), tokens.get("refresh_token", "") or ""])
            self.save(tokens)
            return "ok"
        finally:
            self._release_lock()


def credentials_path():
    p = os.environ.get("CLAUDE_CREDENTIALS_FILE", "").strip()
    if p:
        return os.path.expanduser(p)
    d = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    if d:
        return os.path.join(os.path.expanduser(d), ".credentials.json")
    return os.path.join(os.path.expanduser("~"), ".claude", ".credentials.json")


def load_credentials():
    access = os.environ.get("CLAUDE_ACCESS_TOKEN", "").strip()
    if access:
        refresh = os.environ.get("CLAUDE_REFRESH_TOKEN", "").strip()
        _SECRETS.extend([access, refresh])
        return EnvCreds(access, refresh, os.environ.get("CLAUDE_TOKEN_OUT", "").strip())
    path = credentials_path()
    if not os.path.exists(path):
        return None
    c = FileCreds(path)
    c.reload()
    return c


# --------------------------------------------------------------------------
# Parsing (defensive: the endpoint is undocumented)
# --------------------------------------------------------------------------
def num(v):
    """Strict number: int/float only, not bool, finite, within 0..100."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    if v != v or v < 0 or v > 100:
        return None
    return v


def norm_reset(v):
    if not isinstance(v, str) or not v.strip():
        return ""
    s = v.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def slug(name):
    s = re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")
    return s[:40] or "unknown"


def raw_excerpt(obj):
    """Whitelisted fields only, so nothing sensitive can ever leak into data/."""
    keep = {}
    if isinstance(obj, dict):
        for k in ("kind", "utilization", "percent", "resets_at"):
            if k in obj and isinstance(obj[k], (str, int, float, bool, type(None))):
                keep[k] = obj[k]
        model = ((obj.get("scope") or {}).get("model") or {}) if isinstance(obj.get("scope"), dict) else {}
        if isinstance(model, dict) and isinstance(model.get("display_name"), str):
            keep["model"] = model["display_name"][:60]
    return json.dumps(keep, separators=(",", ":"))[:500]


def parse_usage(js):
    """Return ordered [(window, pct, reset_iso, raw)] or [] if unrecognized.

    Order: five_hour, per-model weekly buckets, seven_day LAST.  The shared
    site builder treats the final row of a run as the headline when no row is
    labelled `weekly`, so seven_day last keeps the headline meaningful.
    """
    if not isinstance(js, dict):
        return []
    found = {}

    for key in ("five_hour", "seven_day"):
        w = js.get(key)
        if isinstance(w, dict):
            pct = num(w.get("utilization"))
            if pct is not None:
                found[key] = (pct, norm_reset(w.get("resets_at")), raw_excerpt(w))

    limits = js.get("limits")
    models = []
    if isinstance(limits, list):
        for e in limits:
            if not isinstance(e, dict):
                continue
            pct = num(e.get("percent"))
            if pct is None:
                continue
            scope = e.get("scope")
            model = None
            if isinstance(scope, dict) and isinstance(scope.get("model"), dict):
                model = scope["model"].get("display_name")
            if isinstance(model, str) and model.strip():
                name = "weekly_" + slug(model)  # scoped buckets are weekly
                if all(name != m[0] for m in models):
                    models.append((name, pct, norm_reset(e.get("resets_at")), raw_excerpt(e)))
            else:
                kind = slug(e.get("kind", ""))
                if kind in ("five_hour", "seven_day") and kind not in found:
                    found[kind] = (pct, norm_reset(e.get("resets_at")), raw_excerpt(e))

    rows = []
    if "five_hour" in found:
        rows.append(("five_hour",) + found["five_hour"])
    rows.extend(models)
    if "seven_day" in found:
        rows.append(("seven_day",) + found["seven_day"])
    return rows


# --------------------------------------------------------------------------
# Run lock + CSV
# --------------------------------------------------------------------------
class Lock:
    """Portable O_EXCL lockfile with stale takeover, so two overlapping sampler
    runs on this machine cannot double-rotate the refresh token."""

    def __enter__(self):
        for _ in range(2):
            try:
                self.fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, str(os.getpid()).encode())
                return self
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(LOCK_PATH) > LOCK_STALE_S:
                        os.unlink(LOCK_PATH)
                        continue
                except OSError:
                    pass
                break
        raise BlockingIOError("another sampler run holds the lock")

    def __exit__(self, *a):
        try:
            os.close(self.fd)
            os.unlink(LOCK_PATH)
        except OSError:
            pass


def last_timestamp(path):
    if not os.path.exists(path):
        return None
    last = None
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                last = datetime.fromisoformat(r["timestamp_utc"])
            except Exception:
                continue
    return last


def append_rows(path, now, plan, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new_file = not os.path.exists(path) or os.path.getsize(path) == 0
    needs_nl = False
    if not new_file:
        with open(path, "rb") as f:
            f.seek(-1, os.SEEK_END)
            needs_nl = f.read(1) not in (b"\n", b"\r")
    with open(path, "a", newline="", encoding="utf-8") as f:
        if needs_nl:
            f.write("\n")
        w = csv.writer(f, lineterminator="\n")
        if new_file:
            w.writerow(HEADER)
        ts = now.isoformat(timespec="seconds")
        for window, pct, reset_iso, raw in rows:
            w.writerow([ts, f"{pct:g}", plan, reset_iso, window, raw])


# --------------------------------------------------------------------------
def do_refresh(creds):
    """Refresh via the right path for the credential source.  Returns True if
    creds.access is now usable."""
    if isinstance(creds, FileCreds):
        outcome = creds.refresh_locked()
        if outcome in ("ok", "reused"):
            return True
        status_line(status="nothing_written",
                    reason="refresh_lock_busy" if outcome == "locked" else "refresh_failed_relogin_needed")
        return False
    if not creds.refresh:
        status_line(status="nothing_written", reason="401_and_no_refresh_token")
        return False
    tokens = refresh_tokens(creds.refresh)
    if not tokens:
        status_line(status="nothing_written", reason="refresh_failed_relogin_needed")
        return False
    _SECRETS.extend([tokens.get("access_token", ""), tokens.get("refresh_token", "") or ""])
    creds.save(tokens)  # persist BEFORE using: the old refresh token is already dead
    creds.access = tokens["access_token"]
    return True


def run():
    no_refresh = os.environ.get("CLAUDE_NO_REFRESH", "").strip() == "1"
    try:
        creds = load_credentials()
    except Exception as e:
        log(f"credentials unreadable: {type(e).__name__}: {e}")
        status_line(status="nothing_written", reason="credentials_unreadable")
        return 0
    if creds is None:
        status_line(status="nothing_written", reason="no_credentials", looked_at=credentials_path())
        return 0
    plan = os.environ.get("CLAUDE_PLAN", "").strip() or creds.plan or "unknown"

    now = datetime.now(timezone.utc)
    prev = last_timestamp(CSV_PATH)
    if prev is not None and prev.tzinfo is not None and (now - prev).total_seconds() < MIN_GAP_S:
        status_line(status="skipped", reason="previous_sample_under_2min_old")
        return 0

    refreshed = False
    if isinstance(creds, FileCreds) and creds.about_to_expire() and not no_refresh:
        if not do_refresh(creds):
            return 0
        refreshed = True

    status, js = get_usage(creds.access)
    if status == 401 and not refreshed:
        if no_refresh:
            status_line(status="nothing_written", reason="401_and_refresh_disabled")
            return 0
        if not do_refresh(creds):
            return 0
        status, js = get_usage(creds.access)
    if status == 401:
        status_line(status="nothing_written", reason="401_after_refresh")
        return 0
    if status != 200:
        status_line(status="nothing_written", reason=f"http_{status}")
        return 0

    rows = parse_usage(js)
    if not rows:
        keys = sorted(js.keys())[:12] if isinstance(js, dict) else type(js).__name__
        log(f"unrecognized usage shape; top-level keys: {keys}")
        status_line(status="nothing_written", reason="unrecognized_shape")
        return 0

    append_rows(CSV_PATH, now, plan, rows)
    status_line(status="ok", rows=len(rows), windows=",".join(r[0] for r in rows),
                plan=plan, creds=creds.describe(), refreshed=str(refreshed).lower())
    return 0


def main():
    try:
        with Lock():
            return run()
    except BlockingIOError as e:
        status_line(status="skipped", reason="locked")
        log(str(e))
        return 0
    except Exception as e:  # never fail the schedule on a surprise
        log(f"unexpected {type(e).__name__}: {e}")
        status_line(status="nothing_written", reason="unexpected_error")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
