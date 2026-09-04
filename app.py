"""
Job Search Dashboard — Flask web app.

Reads job_tracker.json from the GitHub repo raw URL (set via GITHUB_REPO env var)
and renders a live dashboard. Data is cached in memory for CACHE_TTL seconds to
avoid hammering the GitHub CDN on every page load.

Environment variables (set in Render dashboard):
    GITHUB_REPO    dpgit07/job-search-agent   (default)
    GITHUB_BRANCH  main                         (default)
"""

import os
import time
import requests
from datetime import datetime, timezone, date, timedelta
from flask import Flask, render_template, jsonify, redirect, url_for

app = Flask(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
GITHUB_REPO   = os.environ.get("GITHUB_REPO",   "dpgit07/job-search-agent")
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")
TRACKER_URL   = (
    f"https://raw.githubusercontent.com/{GITHUB_REPO}"
    f"/{GITHUB_BRANCH}/data/job_tracker.json"
)
CACHE_TTL = 300  # seconds — refresh data every 5 minutes

# ── In-memory cache ───────────────────────────────────────────────────────────
_cache: dict = {"data": None, "ts": 0.0}

EMPTY_TRACKER = {"jobs": [], "last_scan": None, "total_scans": 0}


def load_tracker() -> dict:
    """Fetch tracker JSON from GitHub, with a 5-minute in-memory cache."""
    now = time.time()
    if _cache["data"] is None or now - _cache["ts"] > CACHE_TTL:
        try:
            r = requests.get(TRACKER_URL, timeout=10)
            r.raise_for_status()
            _cache["data"] = r.json()
            _cache["ts"]   = now
        except Exception as e:
            app.logger.warning(f"Could not fetch tracker: {e}")
            if _cache["data"] is None:
                _cache["data"] = EMPTY_TRACKER
    return _cache["data"]


# ── Template filters ──────────────────────────────────────────────────────────

@app.template_filter("fit_class")
def fit_class(score: int) -> str:
    if score >= 85:
        return "fit-high"
    if score >= 70:
        return "fit-mid"
    return "fit-low"


@app.template_filter("badge_class")
def badge_class(status: str) -> str:
    return {
        "new":         "badge-new",
        "reviewing":   "badge-info",
        "tailored":    "badge-info",
        "applied":     "badge-applied",
        "interviewing":"badge-interviewing",
        "offer":       "badge-offer",
        "rejected":    "badge-rejected",
        "withdrawn":   "badge-secondary",
        "archived":    "badge-archived",
    }.get(status, "badge-secondary")


@app.template_filter("fmt_date")
def fmt_date(s: str) -> str:
    if not s:
        return "—"
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.strftime("%b %d")
    except Exception:
        return s[:10]


@app.template_filter("days_ago")
def days_ago(s: str) -> str:
    if not s:
        return ""
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00")).date()
        diff = (date.today() - dt).days
        if diff == 0:
            return "today"
        if diff == 1:
            return "yesterday"
        return f"{diff}d ago"
    except Exception:
        return ""


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def dashboard():
    data = load_tracker()
    jobs = data.get("jobs", [])
    active = [j for j in jobs if j.get("status") != "archived"]

    stats = {
        "total":        len(active),
        "new":          sum(1 for j in active if j.get("status") == "new"),
        "applied":      sum(1 for j in active if j.get("status") in ("applied", "tailored")),
        "interviewing": sum(1 for j in active if j.get("status") == "interviewing"),
        "offers":       sum(1 for j in active if j.get("status") == "offer"),
        "rejected":     sum(1 for j in active if j.get("status") == "rejected"),
    }

    today_d  = date.today()
    two_ago  = (today_d - timedelta(days=2)).isoformat()
    seven_ago = (today_d - timedelta(days=7)).isoformat()
    thirty_ago = (today_d - timedelta(days=30)).isoformat()
    today_str = today_d.isoformat()

    time_stats = {
        "today":    sum(1 for j in active if j.get("discovered_date", "")[:10] >= today_str),
        "last_2d":  sum(1 for j in active if j.get("discovered_date", "")[:10] >= two_ago),
        "last_7d":  sum(1 for j in active if j.get("discovered_date", "")[:10] >= seven_ago),
        "last_30d": sum(1 for j in active if j.get("discovered_date", "")[:10] >= thirty_ago),
        "archived": sum(1 for j in jobs   if j.get("status") == "archived"),
    }

    pipeline_statuses = ("applied", "tailored", "reviewing", "interviewing", "offer")
    pipeline_order = {"offer": 0, "interviewing": 1, "applied": 2, "tailored": 3, "reviewing": 4}
    pipeline = sorted(
        [j for j in jobs if j.get("status") in pipeline_statuses],
        key=lambda j: (pipeline_order.get(j.get("status", ""), 9), -(j.get("fit_score", 0))),
    )

    high_priority = sorted(
        [j for j in active if j.get("fit_score", 0) >= 85 and j.get("status") == "new"],
        key=lambda j: j.get("fit_score", 0),
        reverse=True,
    )[:10]

    follow_ups = [
        j for j in active
        if j.get("follow_up_date")
        and j["follow_up_date"] <= today_str
        and j.get("status") not in ("rejected", "withdrawn", "offer")
    ]

    recent = sorted(
        active, key=lambda j: j.get("discovered_date", ""), reverse=True
    )[:8]

    return render_template(
        "dashboard.html",
        stats=stats,
        time_stats=time_stats,
        pipeline=pipeline,
        high_priority=high_priority,
        follow_ups=follow_ups,
        recent=recent,
        last_scan=data.get("last_scan"),
        total_scans=data.get("total_scans", 0),
    )


@app.route("/jobs")
def jobs_page():
    data = load_tracker()
    all_jobs = sorted(
        data.get("jobs", []),
        key=lambda j: j.get("fit_score", 0),
        reverse=True,
    )
    statuses = sorted({j.get("status", "new") for j in all_jobs})
    return render_template("jobs.html", jobs=all_jobs, statuses=statuses)


@app.route("/api/jobs")
def api_jobs():
    data = load_tracker()
    return jsonify(data.get("jobs", []))


@app.route("/api/stats")
def api_stats():
    data = load_tracker()
    jobs = data.get("jobs", [])
    by_status = {}
    for j in jobs:
        s = j.get("status", "new")
        by_status[s] = by_status.get(s, 0) + 1

    avg_fit = (
        sum(j.get("fit_score", 0) for j in jobs) / len(jobs)
        if jobs else 0
    )
    return jsonify({
        "total":      len(jobs),
        "by_status":  by_status,
        "avg_fit":    round(avg_fit, 1),
        "last_scan":  data.get("last_scan"),
        "total_scans": data.get("total_scans", 0),
    })


@app.route("/api/refresh")
def api_refresh():
    """Force a cache bust so the next page load fetches fresh data."""
    _cache["ts"] = 0.0
    return redirect(url_for("dashboard"))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
