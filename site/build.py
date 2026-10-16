#!/usr/bin/env python3
"""Build the unified assistant-usage dashboard.

Reads data/*/usage.csv (see docs/DATA_CONTRACT.md) and writes a self-contained
index.html: one card per assistant plus a combined "% of own limit" trendline.
Lanes with no data yet render a "waiting for first sample" placeholder.
"""
import csv
import html
import json
import os
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

HOME = os.path.expanduser("~")
# Repo root = parent of the site/ directory this script lives in.
# (Must be repo-relative: on GitHub runners $HOME is not the repo.)
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
OUT = os.path.join(BASE, "index.html")

LANES = [
    ("muse", "Muse", "#5aa2ff"),
    ("claude", "Claude", "#e8935a"),
    ("grok", "Grok", "#6fd08c"),
]

# Estimated allowance ratio vs each platform's free tier, where known.
# Muse: Power ~= 5x the Free weekly allowance (both figures are estimates --
# the API exposes only % of allowance, never token counts).
FREE_EQUIV_RATIO = {"muse": 5.0}
LOCAL_TZ = "America/Indiana/Indianapolis"


def load_lane(lane):
    path = os.path.join(DATA, lane, "usage.csv")
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            try:
                ts = datetime.fromisoformat(r["timestamp_utc"])
            except Exception:
                continue
            try:
                pct = float(r["usage_pct"]) if r.get("usage_pct") else None
            except Exception:
                pct = None
            rows.append({
                "ts": ts,
                "pct": pct,
                "plan": r.get("plan", ""),
                "reset_iso": r.get("reset_iso", ""),
                "window": r.get("window") or "weekly",
            })
    rows.sort(key=lambda r: r["ts"])
    return rows


def linreg_slope_pct_per_hour(pts):
    """Slope of least-squares fit over headline points, in % per hour."""
    n = len(pts)
    if n < 2:
        return 0.0
    t0 = pts[0]["ts"]
    xs = [(p["ts"] - t0).total_seconds() / 3600.0 for p in pts]
    ys = [p["pct"] for p in pts]
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return 0.0
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return sxy / sxx


def main():
    now = datetime.now(timezone.utc)
    lanes = {}
    for lane, label, color in LANES:
        rows = [r for r in load_lane(lane) if r["pct"] is not None]
        # Headline series: the lane's weekly window. Claude writes five_hour /
        # seven_day / weekly_<model> windows, so accept seven_day as weekly.
        weekly = [r for r in rows if r["window"] in ("weekly", "seven_day")] or rows
        last = weekly[-1] if weekly else None
        reset_in = None
        if last and last["reset_iso"]:
            try:
                rt = datetime.fromisoformat(last["reset_iso"])
                reset_in = (rt - now).total_seconds() / 3600.0
            except Exception:
                pass
        slope = linreg_slope_pct_per_hour(weekly)
        # Time bar: fraction of the current window already elapsed. All
        # current lanes run 7-day windows; keyed off the window name so a
        # future lane with a different window simply gets no time bar.
        WINDOW_HOURS = {"weekly": 168.0, "seven_day": 168.0}
        time_pct = time_start = time_reset = None
        win_name = weekly[0]["window"] if weekly else None
        if last and reset_in is not None and win_name in WINDOW_HOURS:
            total_h = WINDOW_HOURS[win_name]
            time_pct = round(min(100.0, max(0.0, (1 - reset_in / total_h) * 100)), 1)
            try:
                rt = datetime.fromisoformat(last["reset_iso"])
                et = ZoneInfo(LOCAL_TZ)
                time_start = (rt - timedelta(hours=total_h)).astimezone(et).strftime("%b %d")
                time_reset = rt.astimezone(et).strftime("%b %d · %I:%M %p")
            except Exception:
                time_pct = time_start = time_reset = None
        last_pct = last["pct"] if last else None
        hit_h = ((100.0 - last_pct) / slope
                 if (last and slope > 0 and last_pct < 100) else None)
        proj = None
        if last and slope > 0 and last_pct < 100 and last["reset_iso"]:
            try:
                rt = datetime.fromisoformat(last["reset_iso"])
                t0, p0 = last["ts"], last_pct
                t_end, p_end = rt, p0 + slope * ((rt - t0).total_seconds() / 3600.0)
                if p_end > 100:
                    t_end = t0 + timedelta(hours=(100 - p0) / slope)
                    p_end = 100.0
                if t_end > t0:
                    proj = {
                        "from": {"t": t0.isoformat(timespec="seconds"), "pct": round(p0, 2)},
                        "to": {"t": t_end.isoformat(timespec="seconds"),
                               "pct": round(min(p_end, 100), 2)},
                    }
            except Exception:
                pass
        lanes[lane] = {
            "label": label, "color": color,
            "latest": ({
                "pct": last_pct, "plan": last["plan"],
                "reset_iso": last["reset_iso"],
                "reset_in_h": round(reset_in, 1) if reset_in else None,
                "at": last["ts"].isoformat(timespec="seconds"),
            } if last else None),
            "stats": {
                "burn_per_hour": round(slope, 3),
                "hours_to_100": round(hit_h, 2) if hit_h is not None else None,
                "samples": len(weekly),
                "time_pct": time_pct, "time_start": time_start, "time_reset": time_reset,
                **({"free_equiv": round(last_pct * FREE_EQUIV_RATIO[lane], 1),
                    "free_marker": round(100.0 / FREE_EQUIV_RATIO[lane], 1)}
                   if lane in FREE_EQUIV_RATIO and last_pct is not None else {}),
            },
            "projection": proj,
            "points": [{"t": r["ts"].isoformat(timespec="seconds"), "pct": r["pct"]}
                       for r in weekly],
        }

    payload = {"generated_at": now.isoformat(timespec="seconds"), "lanes": lanes}
    built = now.astimezone(ZoneInfo(LOCAL_TZ)).strftime("%b %d, %Y %I:%M %p %Z")

    page = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="manifest" href="manifest.webmanifest">
<meta name="theme-color" content="#0f1420">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="AI Usage">
<link rel="apple-touch-icon" href="icons/apple-touch-icon.png">
<link rel="icon" type="image/png" sizes="32x32" href="icons/favicon-32.png">
<title>Assistant Usage</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
<script>
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => navigator.serviceWorker.register('sw.js').catch(() => {}));
}
</script>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
         background:#0f1420; color:#e8ecf4; }
  .wrap { max-width:1080px; margin:0 auto; padding:24px 16px 64px; }
  h1 { font-size:1.6rem; margin:0 0 4px; }
  .sub { color:#9aa3b5; font-size:.85rem; margin:0 0 20px; }
  .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:12px; margin-bottom:20px; }
  .card { background:#182032; border:1px solid #26314a; border-radius:12px; padding:14px 16px; }
  .card .k { font-size:.72rem; text-transform:uppercase; letter-spacing:.06em; color:#9aa3b5; margin-bottom:8px; }
  .card .note { font-size:.78rem; color:#9aa3b5; margin-top:4px; }
  .card.pending { opacity:.65; }
  .toprow { display:grid; grid-template-columns:auto 1fr; gap:12px; align-items:stretch; }
  .bignum { font-size:3.2rem; font-weight:700; line-height:1; align-self:end; }
  .bignum .pct { font-size:1.6rem; font-weight:700; }
  .k .plan { text-transform:none; letter-spacing:0; }
  .pills { display:grid; grid-template-columns:1fr 1fr; grid-template-rows:1fr 1fr; gap:6px; }
  .chip { display:flex; align-items:center; white-space:nowrap; overflow:hidden; background:#131b2c; border:1px solid #26314a; border-radius:999px; padding:4px 10px; font-size:.78rem; color:#9aa3b5; }
  .chip b { color:#e8ecf4; font-weight:600; margin:0 .35em; }
  .fuelwrap { position:relative; margin-top:26px; }
  .fuelbar { height:14px; border-radius:7px; overflow:hidden;
             background:linear-gradient(90deg, rgba(111,208,140,.16) 0 70%, rgba(245,177,76,.20) 70% 90%, rgba(242,109,109,.24) 90% 100%); }
  .fuelbar > div { height:100%; border-radius:7px; }
  .freemark { position:absolute; top:-4px; width:2px; height:22px; background:#e8ecf4; opacity:.85; }
  .freemark span { position:absolute; bottom:25px; left:50%; transform:translateX(-50%); font-size:.65rem; letter-spacing:.08em; color:#9aa3b5; text-transform:uppercase; }
  .barlab { display:flex; justify-content:space-between; font-size:.75rem; color:#9aa3b5; margin-top:6px; }
  .barlab b { color:#e8ecf4; }
  .timebar { height:6px; border-radius:3px; background:#1d2740; margin-top:5px; overflow:hidden; }
  .timebar > div { height:100%; border-radius:3px; opacity:.55; }
  .timelab { display:flex; justify-content:space-between; font-size:.68rem; color:#66708a; margin-top:4px; }
  .panel { background:#131b2c; border:1px solid #26314a; border-radius:14px; padding:18px; margin-bottom:20px; }
  .panel h2 { font-size:1.05rem; margin:0 0 12px; }
  canvas { width:100% !important; height:360px !important; }
  .foot { color:#66708a; font-size:.75rem; margin-top:28px; }
  @media (max-width:640px){ canvas{ height:280px !important; } }
</style>
</head>
<body>
<div class="wrap">
  <h1>Assistant Usage</h1>
  <p class="sub">Subscription usage across Jeff's AI assistants &middot; last updated __BUILT__</p>
  <div class="cards" id="cards"></div>
  <div class="panel">
    <h2>% of own limit — all assistants</h2>
    <canvas id="chart"></canvas>
  </div>
  <p class="foot">Each assistant samples its own platform's subscription every ~15 minutes.
  Percentages are % of that platform's own limit, so the lines are comparable as "how hot
  each subscription is running". Burn rate is a least-squares fit over each lane's headline
  series; dashed lines project it to the reset (capped at 100%). The Muse card's
  free-tier equivalence uses the estimated 5x Power/Free allowance ratio, and the
  "Free" tick on its bar marks where one full Free-tier week runs out (20% of the
  Power bar). One repo, one lane per assistant:
  <a href="https://github.com/daboodah-oss/assistant-usage" style="color:#5aa2ff">daboodah-oss/assistant-usage</a>.</p>
</div>
<script>
const DATA = __DATA__;
const fmtDur = h => {
  if (h == null || h < 0) return '—';
  if (h < 1) return Math.round(h*60) + ' min';
  if (h < 48) { const hh=Math.floor(h), mm=Math.round((h-hh)*60); return mm? hh+'h '+String(mm).padStart(2,'0')+'m' : hh+'h'; }
  return (h/24).toFixed(1) + ' days';
};
function statusColor(pct){ return pct >= 90 ? '#f26d6d' : pct >= 70 ? '#f5b14c' : '#6fd08c'; }
const cards = document.getElementById('cards');
cards.innerHTML = Object.entries(DATA.lanes).map(([lane, L]) => {
  if (!L.latest) return `<div class="card pending"><div class="k">${L.label}</div><div class="bignum">—</div><div class="note">waiting for first sample</div></div>`;
  const s = L.latest, st = L.stats || {};
  const cls = s.pct >= 90 ? 'color:#f26d6d' : s.pct >= 70 ? 'color:#f5b14c' : '';
  const rem = Math.max(0, 100 - s.pct);
  const plan = s.plan ? (s.plan === s.plan.toLowerCase() ? s.plan.charAt(0).toUpperCase() + s.plan.slice(1) : s.plan) : 'limit';
  const fourth = st.free_equiv != null
    ? `<span class="chip">Free equiv <b>≈${st.free_equiv}%</b></span>`
    : `<span class="chip">Samples <b>${st.samples != null ? st.samples : '—'}</b></span>`;
  const chips = [
    `<span class="chip">Burn <b>${st.burn_per_hour != null ? st.burn_per_hour + '%/h' : '—'}</b></span>`,
    st.hours_to_100 != null
      ? `<span class="chip">100% in <b>${fmtDur(st.hours_to_100)}</b></span>`
      : `<span class="chip">100% in <b>—</b> ${st.burn_per_hour < 0 ? 'falling' : 'flat'}</span>`,
    `<span class="chip">Resets <b>${fmtDur(s.reset_in_h)}</b></span>`,
    fourth
  ].join('');
  const samplesNote = st.free_equiv != null && st.samples != null ? ` · ${st.samples} samples` : '';
  const mark = st.free_marker != null
    ? `<div class="freemark" style="left:${st.free_marker}%" title="One full Free-tier week ends here (${st.free_marker}% of the Power bar)"><span>Free</span></div>` : '';
  return `<div class="card"><div class="k"><span style="color:${L.color}">●</span> ${L.label} <span class="plan">– ${plan}</span></div>
    <div class="toprow"><div class="bignum" style="${cls}">${s.pct}<span class="pct">%</span></div><div class="pills">${chips}</div></div>
    <div class="fuelwrap">${mark}<div class="fuelbar"><div style="width:${s.pct}%; background:${statusColor(s.pct)}"></div></div>${st.time_pct != null ? `<div class="timebar" title="Time elapsed in the current 7-day window"><div style="width:${st.time_pct}%; background:${L.color}"></div></div>` : ''}</div>
    <div class="barlab"><span>0%</span><span><b>${rem.toFixed(0)}%</b> remaining${samplesNote}</span><span>100%</span></div>${st.time_pct != null ? `<div class="timelab"><span>${st.time_start}</span><span>resets ${st.time_reset}</span></div>` : ''}</div>`;
}).join('');
const datasets = Object.entries(DATA.lanes)
  .filter(([lane, L]) => L.points.length)
  .map(([lane, L]) => ({
    label: L.label,
    data: L.points.map(p => ({x: new Date(p.t), y: p.pct})),
    borderColor: L.color, backgroundColor: L.color + '22',
    fill: false, tension: .25, pointRadius: 0, borderWidth: 2
  }));
// Dashed projection per lane: current burn rate extended to the reset (or 100%).
Object.entries(DATA.lanes).forEach(([lane, L]) => {
  if (!L.projection) return;
  datasets.push({
    label: L.label + ' projected',
    data: [{x: new Date(L.projection.from.t), y: L.projection.from.pct},
           {x: new Date(L.projection.to.t), y: L.projection.to.pct}],
    borderColor: L.color, borderDash: [6, 4], fill: false,
    tension: 0, pointRadius: 0, borderWidth: 1.5
  });
});
new Chart(document.getElementById('chart'), {
  type: 'line',
  data: { datasets },
  options: {
    responsive: true, maintainAspectRatio: false,
    plugins: { legend: { labels: { color:'#9aa3b5' } } },
    scales: {
      x: { type: 'time', time: { unit: 'day', tooltipFormat: 'MMM d, h:mm a' },
           ticks: { color:'#9aa3b5' }, grid: { color:'#1d2740' } },
      y: { min: 0, max: 105, ticks: { color:'#9aa3b5', callback: v => v + '%' }, grid: { color:'#1d2740' } }
    }
  }
});
</script>
</body>
</html>
"""
    page = page.replace("__BUILT__", built).replace("__DATA__", json.dumps(payload))
    with open(OUT, "w") as f:
        f.write(page)
    total = sum(len(l["points"]) for l in lanes.values())
    print(f"site: wrote {OUT} ({total} points across {len(lanes)} lanes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
