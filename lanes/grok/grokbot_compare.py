#!/usr/bin/env python3
"""grok_bot source comparison: platform reading (option A) vs billing weekly_GrokBot (option B).

Jeff's decision rule (Nov 15, 2026):
- Option A from the Nov 21 reset (Sat Nov 21, 9:41 PM ET = 2026-11-22T02:41:26Z): grok_bot rows
  come from the platform reading, appended on the wake, pushed by the pusher.
- Compare platform vs billing weekly_GrokBot at every paired reading that week.
- At the end of the window:
    any pair differs by more than 1 point  -> KEEP A; report the divergent pairs (times, both values)
    else >= 50 pairs                        -> SWITCH to B at the next reset: amend the grok_bot line
                                               in docs/DATA_CONTRACT.md in the same change, set
                                               GROK_BOT_SOURCE=billing in lanes/grok/feed.conf
                                               (raw source=billing_product), note it in the receipt
    else (< 50 pairs)                       -> extend the window one more week automatically
A pair = one feed-run invocation that has BOTH a platform percent (--grok-bot-pct) and a billing
reading carrying products.GrokBot, taken within 10 minutes of each other, with the billing
reading's period_end equal to the window's end. Billing readings that omit GrokBot are not
pairs (unknown is not zero). Pairs before the window are logged to pre-window.jsonl only.

State (box only, never in the repo): <state-dir>/compare.json, pairs.jsonl, pre-window.jsonl
Usage:
  grokbot_compare.py record --platform-pct P --platform-ts ISO --tracker-log PATH
  grokbot_compare.py evaluate            (prints one COMPARE line; idempotent; ACTION lines repeat
                                         every run until Keela runs `ack` after acting on them)
  grokbot_compare.py ack
"""
import argparse, json, os, sys
from datetime import datetime, timedelta, timezone

WINDOW_START = "2026-11-22T02:41:26+00:00"   # Sat Nov 21, 2026, 9:41 PM ET (Ultra weekly reset)
WEEK = timedelta(days=7)
MAX_DIFF = 1.0
MIN_PAIRS = 50
PAIR_SKEW = timedelta(minutes=10)


def P(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def load(d):
    p = os.path.join(d, "compare.json")
    if os.path.exists(p):
        return json.load(open(p))
    s = P(WINDOW_START)
    return {"window_start": s.isoformat(), "window_end": (s + WEEK).isoformat(), "extensions": 0,
            "decision": None, "decided_at": None, "divergent": [], "pairs_at_decision": None,
            "history": []}


def save(d, st):
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, "compare.json.tmp")
    json.dump(st, open(tmp, "w"), indent=1)
    os.replace(tmp, os.path.join(d, "compare.json"))


def pairs(d, st):
    out = []
    p = os.path.join(d, "pairs.jsonl")
    if os.path.exists(p):
        s, e = P(st["window_start"]), P(st["window_end"])
        for line in open(p):
            try:
                r = json.loads(line)
            except Exception:
                continue
            if s <= P(r["platform_ts"]) < e:
                out.append(r)
    return out


def newest(log):
    with open(log, "rb") as f:
        f.seek(0, 2); n = f.tell(); f.seek(max(0, n - 65536))
        for line in reversed(f.read().splitlines()):
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("ok"):
                return r
    return None


def cmd_record(a):
    st = load(a.state_dir)
    pts = P(a.platform_ts)
    rec = newest(a.tracker_log)
    if not rec:
        print("COMPARE record=skip reason=no_ok_billing_reading"); return 0
    bts = P(rec["ts"])
    gb = (rec.get("products") or {}).get("GrokBot")
    if not isinstance(gb, (int, float)):
        print("COMPARE record=skip reason=billing_omits_GrokBot"); return 0
    if abs(bts - pts) > PAIR_SKEW:
        print("COMPARE record=skip reason=readings_%ds_apart" % abs((bts - pts).total_seconds())); return 0
    row = {"platform_ts": pts.astimezone(timezone.utc).isoformat(), "platform_pct": float(a.platform_pct),
           "billing_ts": bts.astimezone(timezone.utc).isoformat(), "billing_pct": float(gb),
           "billing_period_end": rec.get("period_end"),
           "diff": round(float(a.platform_pct) - float(gb), 2)}
    s, e = P(st["window_start"]), P(st["window_end"])
    in_window = s <= pts < e and st["decision"] is None
    if in_window and rec.get("period_end") and abs(P(rec["period_end"]) - e) > timedelta(hours=1):
        in_window = False; row["note"] = "billing period_end does not match window end"
    fn = "pairs.jsonl" if in_window else "pre-window.jsonl"
    os.makedirs(a.state_dir, exist_ok=True)
    with open(os.path.join(a.state_dir, fn), "a") as f:
        f.write(json.dumps(row) + "\n")
    print("COMPARE record=%s diff=%s" % ("pair" if in_window else "pre_window", row["diff"]))
    return 0


def cmd_evaluate(a):
    st = load(a.state_dir)
    now = datetime.now(timezone.utc) if not a.now else P(a.now)
    pr = pairs(a.state_dir, st)
    div = [r for r in pr if abs(r["diff"]) > MAX_DIFF]
    if st["decision"]:
        print("COMPARE decision=%s decided_at=%s pairs=%s%s" % (st["decision"], st["decided_at"], st["pairs_at_decision"],
                                                             " acked" if st.get("acked") else ""))
        if st.get("acked"):
            return 0
        if st["decision"] == "switch_to_B":
            print("ACTION grokbot_switch_to_B: amend the grok_bot line in docs/DATA_CONTRACT.md and set "
                  "GROK_BOT_SOURCE=billing in lanes/grok/feed.conf in ONE change; note it in the receipt")
        elif st["decision"] == "keep_A_divergent":
            print("ACTION grokbot_report_divergence_to_Jeff: %s" % json.dumps(st["divergent"])[:1500])
        return 0
    if now < P(st["window_start"]):
        print("COMPARE state=not_started window=%s..%s" % (st["window_start"], st["window_end"])); return 0
    if now < P(st["window_end"]):
        print("COMPARE state=running pairs=%d divergent=%d max_abs_diff=%s window_end=%s ext=%d"
              % (len(pr), len(div), max([abs(r["diff"]) for r in pr], default="-"), st["window_end"], st["extensions"]))
        return 0
    # window over: apply the rule
    if div:
        st.update(decision="keep_A_divergent", decided_at=now.isoformat(), pairs_at_decision=len(pr),
                  divergent=[{k: r[k] for k in ("platform_ts", "platform_pct", "billing_ts", "billing_pct", "diff")} for r in div])
    elif len(pr) >= MIN_PAIRS:
        st.update(decision="switch_to_B", decided_at=now.isoformat(), pairs_at_decision=len(pr))
    else:
        st["history"].append({"window_end": st["window_end"], "pairs": len(pr), "extended_at": now.isoformat()})
        st["window_end"] = (P(st["window_end"]) + WEEK).isoformat()
        st["extensions"] += 1
        save(a.state_dir, st)
        print("COMPARE state=extended pairs=%d (<%d) new_window_end=%s ext=%d%s" % (
            len(pr), MIN_PAIRS, st["window_end"], st["extensions"],
            " note=extended_more_than_once_tell_Keela" if st["extensions"] > 1 else ""))
        return 0
    save(a.state_dir, st)
    return cmd_evaluate(a)


def cmd_ack(a):
    st = load(a.state_dir)
    if not st["decision"]:
        print("COMPARE ack=refused reason=no_decision_yet"); return 1
    st["acked"] = datetime.now(timezone.utc).isoformat(); save(a.state_dir, st)
    print("COMPARE ack=ok decision=%s" % st["decision"]); return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-dir", default=os.environ.get("GROK_FEED_STATE", "/workspace/grok-feed/state") + "/grokbot-compare")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("--platform-pct", required=True)
    r.add_argument("--platform-ts", required=True)
    r.add_argument("--tracker-log", default="/workspace/grok-usage/usage_log.jsonl")
    e = sub.add_parser("evaluate")
    e.add_argument("--now", help="ISO time, for tests")
    sub.add_parser("ack", help="Keela: the ACTION was carried out/reported; stop repeating it")
    a = ap.parse_args()
    return {"record": cmd_record, "evaluate": cmd_evaluate, "ack": cmd_ack}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
