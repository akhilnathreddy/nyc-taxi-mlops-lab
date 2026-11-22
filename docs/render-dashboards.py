#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["matplotlib==3.9.2", "certifi==2024.8.30"]
# ///
"""Render the Ride app dashboard's queries for 2026-11-22 as PNGs for the README.

Reads Grafana Cloud's Prometheus API with the lab/grafana secret (never printed), with Learner Lab
credentials in the environment. The windows and event times are 2026-11-22's (S5). Usage:
  docs/render-dashboards.py docs/images
"""

import base64
import json
import ssl
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import certifi
import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)

secret = json.loads(subprocess.check_output(
    ["aws", "secretsmanager", "get-secret-value", "--region", "us-east-1", "--secret-id", "lab/grafana",
     "--query", "SecretString", "--output", "text"]))
BASE = secret["url"].removesuffix("/push")
AUTH = "Basic " + base64.b64encode(f"{secret['user']}:{secret['token']}".encode()).decode()
CTX = ssl.create_default_context(cafile=certifi.where())
del secret

# Palette (dataviz reference, light mode): series in fixed order, status red only for the alert line.
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
RED = "#e34948"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "axes.titlecolor": INK, "axes.titlesize": 11,
    "axes.titleweight": "bold", "axes.titlelocation": "left", "axes.grid": True, "grid.color": GRID,
    "grid.linewidth": 0.6, "xtick.color": INK2, "ytick.color": INK2, "font.size": 9, "lines.linewidth": 2,
    "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False, "legend.fontsize": 9,
})


def ts(hms: str) -> datetime:
    return datetime.fromisoformat(f"2026-11-22T{hms}+00:00")


def query_range(expr: str, start: str, end: str, step: str = "15s") -> list[dict]:
    qs = urllib.parse.urlencode({"query": expr, "start": ts(start).timestamp(), "end": ts(end).timestamp(), "step": step})
    req = urllib.request.Request(f"{BASE}/api/v1/query_range?{qs}", headers={"Authorization": AUTH})
    with urllib.request.urlopen(req, context=CTX, timeout=60) as r:
        body = json.load(r)
    if body.get("status") != "success":
        raise RuntimeError(f"query failed: {expr}: {body}")
    return body["data"]["result"]


def series(result: list[dict], label: str | None = None) -> dict[str, tuple[list, list]]:
    out = {}
    for s in result:
        key = s["metric"].get(label, "") if label else "value"
        xs = [datetime.fromtimestamp(float(t), timezone.utc) for t, _ in s["values"]]
        ys = [float(v) if v not in ("NaN", "+Inf", "-Inf") else float("nan") for _, v in s["values"]]
        out[key] = (xs, ys)
    return out


def time_axis(ax, fmt="%H:%M"):
    ax.xaxis.set_major_formatter(mdates.DateFormatter(fmt, tz=timezone.utc))
    ax.set_xlabel("UTC, 2026-11-22")


def mark_events(ax, events, top=True):
    for t, text in events:
        ax.axvline(ts(t), color=INK2, linewidth=1, linestyle=(0, (3, 3)), zorder=1)
    if top:  # staggered, so events seconds apart don't print over each other
        for i, (t, text) in enumerate(events):
            ax.annotate(text, xy=(ts(t), 1 - 0.09 * i), xycoords=("data", "axes fraction"), xytext=(4, 0),
                        textcoords="offset points", va="top", fontsize=8, color=INK2)


def footer(fig, text):
    fig.text(0.01, -0.01, text, fontsize=7.5, color=INK2, va="top")


# 1. The fire test (S5 step 5): serving-champion stopped while 5 requests/s came in.
START, END = "12:02:00", "12:24:00"
EVENTS = [("12:09:44", "① break: serving-champion stopped"), ("12:14:35", "② alert fires"), ("12:14:46", "③ fix: started again"),
          ("12:21:47", "④ alert resolves; test traffic stopped")]
quotes = series(query_range("sum by (source) (rate(lab_predictions_total[1m]))", START, END), "source")
burn1h = series(query_range("slo:predict_fallback:ratio_rate1h / 0.01", START, END))
burn5m = series(query_range("slo:predict_fallback:ratio_rate5m / 0.01", START, END))

fig, (a1, a2) = plt.subplots(2, 1, figsize=(10, 6.4), sharex=True, gridspec_kw={"hspace": 0.35})
for key, colour, name in [("model", BLUE, "model (champion v1)"), ("fallback", ORANGE, "fallback (static median)")]:
    if key in quotes:
        a1.plot(*quotes[key], color=colour, label=name)
a1.set_title("Quotes per second, by who answered")
a1.set_ylabel("quotes / s")
a1.set_ylim(0, 7.4)  # headroom above the 5/s lines for the event labels
a1.set_yticks(range(0, 6))
a1.legend(loc="center right")
mark_events(a1, EVENTS)
for (xs, ys), colour, name in [(burn1h["value"], BLUE, "1 h window"), (burn5m["value"], AQUA, "5 min window")]:
    a2.plot(xs, ys, color=colour, label=name)
a2.axhline(14.4, color=RED, linewidth=1.5)
a2.annotate("page when both are above 14.4×", xy=(ts(START), 14.4), xytext=(4, 4), textcoords="offset points", color=RED, fontsize=8)
a2.set_title("Model coverage burn rate (SLO: 99% of quotes from a model)")
a2.set_ylabel("× error budget")
a2.set_ylim(bottom=0)
a2.legend(loc="upper right")
mark_events(a2, EVENTS, top=False)
time_axis(a2)
footer(fig, "Ride app dashboard queries, Grafana Cloud. Every request was HTTP 200: only the model coverage SLO saw the outage.")
fig.savefig(OUT / "s5-fire-test.png", dpi=150, bbox_inches="tight")
plt.close(fig)

# 2. Riders' view over the same window: /predict latency and responses.
pct = {q: series(query_range(f'histogram_quantile({q}, sum by (le) (rate(lab_http_request_duration_seconds_bucket{{route="/predict"}}[1m])))', START, END))["value"]
       for q in ("0.5", "0.95", "0.99")}
codes = series(query_range('sum by (code) (rate(lab_http_requests_total{route="/predict"}[1m]))', START, END), "code")
calls = series(query_range("sum by (outcome) (rate(lab_serving_request_duration_seconds_count[1m]))", START, END), "outcome")

fig, (b1, b2) = plt.subplots(2, 1, figsize=(10, 6.4), sharex=True, gridspec_kw={"hspace": 0.35})
for (q, colour, name) in [("0.5", BLUE, "p50"), ("0.95", ORANGE, "p95"), ("0.99", AQUA, "p99")]:
    xs, ys = pct[q]
    b1.plot(xs, [y * 1000 for y in ys], color=colour, label=name)
b1.axhline(250, color=RED, linewidth=1.5)
b1.annotate("latency SLO: 99% under 250 ms", xy=(ts(START), 250), xytext=(4, -12), textcoords="offset points", color=RED, fontsize=8)
b1.set_title("/predict latency inside the app")
b1.set_ylabel("ms")
b1.set_ylim(0, 300)
b1.legend(loc="center right")
mark_events(b1, EVENTS)
outcome_colours = {"ok": BLUE, "unavailable": ORANGE, "timeout": AQUA, "error": YELLOW}
for key, (xs, ys) in sorted(calls.items(), key=lambda kv: list(outcome_colours).index(kv[0]) if kv[0] in outcome_colours else 9):
    b2.plot(xs, ys, color=outcome_colours.get(key, INK2), label=key)
b2.set_title("The app's calls to serving, by outcome")
b2.set_ylabel("calls / s")
b2.set_ylim(bottom=0)
b2.legend(loc="upper right")
mark_events(b2, EVENTS, top=False)
time_axis(b2)
total_5xx = sum(v for k, (_, ys) in codes.items() if k.startswith("5") for v in ys if v == v)
footer(fig, f"Same window. /predict answered {'no' if total_5xx == 0 else 'some'} 5xx: with serving down, the app fell back within its timeout.")
fig.savefig(OUT / "s5-riders.png", dpi=150, bbox_inches="tight")
plt.close(fig)

# 3. The series budget (S5 step 3): active series per host before and after budget.alloy's rules.
B_START, B_END = "11:20:00", "12:40:00"
active = series(query_range("count by (host) ({__name__=~\".+\", host!=\"\"})", B_START, B_END, "60s"), "host")
fig, c1 = plt.subplots(figsize=(10, 3.8))
for key, colour in [("app", BLUE), ("platform", ORANGE)]:
    if key in active:
        c1.plot(*active[key], color=colour, label=f"{key} host")
mark_events(c1, [("11:43:40", "① budget rules deployed (old series age out of the 5-minute lookback)"),
                 ("11:49:07", "② 3 app deploys in a row, 11:49-11:51")])
c1.set_title("Series sent to Grafana Cloud, per host (free tier: 10,000 in total)")
c1.set_ylabel("series")
c1.set_ylim(bottom=0)
c1.legend(loc="center right")
time_axis(c1)
footer(fig, "count by (host) of every series with a sample in the last 5 minutes. Before: about 3,440. After: about 350, unchanged by the deploys.")
fig.savefig(OUT / "s5-series-budget.png", dpi=150, bbox_inches="tight")
plt.close(fig)

print("wrote", ", ".join(sorted(p.name for p in OUT.glob("s5-*.png"))))
