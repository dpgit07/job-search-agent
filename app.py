"""
Job Search Dashboard — Flask web app.

Reads job_tracker.json from the GitHub repo raw URL and renders a live dashboard.
Status updates are written back to GitHub via the Contents API.

Environment variables (set in Render dashboard):
    GITHUB_REPO    dpgit07/job-search-agent   (default)
    GITHUB_BRANCH  main                         (default)
    GITHUB_TOKEN   <personal access token>      (needed for status updates)
"""

import os
import time
import base64
import requests
from datetime import datetime, timezone, date, timedelta
from flask import Flask, render_template, jsonify, redirect, url_for, request

app = Flask(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
GITHUB_REPO   = os.environ.get("GITHUB_REPO",   "dpgit07/job-search-agent")
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")
GITHUB_TOKEN  = os.environ.get("GITHUB_TOKEN",  "")
TRACKER_PATH  = "data/job_tracker.json"
TRACKER_URL   = (
    f"https://raw.githubusercontent.com/{GITHUB_REPO}"
    f"/{GITHUB_BRANCH}/{TRACKER_PATH}"
)
CACHE_TTL = 300  # seconds

# ── In-memory cache ───────────────────────────────────────────────────────────
_cache: dict = {"data": None, "ts": 0.0}
EMPTY_TRACKER = {"jobs": [], "last_scan": None, "total_scans": 0}


def load_tracker() -> dict:
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


def _github_commit_tracker(data: dict) -> None:
    """Write updated tracker JSON back to GitHub via Contents API."""
    if not GITHUB_TOKEN:
        raise RuntimeError("GITHUB_TOKEN not set — cannot commit to GitHub")

    api_url = (
        f"https://api.github.com/repos/{GITHUB_REPO}"
        f"/contents/{TRACKER_PATH}"
    )
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    # Get current file SHA (required by GitHub API for updates)
    r = requests.get(api_url, headers=headers, params={"ref": GITHUB_BRANCH}, timeout=10)
    r.raise_for_status()
    sha = r.json()["sha"]

    import json
    content = json.dumps(data, indent=2, ensure_ascii=False)
    encoded = base64.b64encode(content.encode()).decode()

    r = requests.put(api_url, headers=headers, json={
        "message": f"chore: update job statuses {date.today()} [skip ci]",
        "content": encoded,
        "sha":     sha,
        "branch":  GITHUB_BRANCH,
    }, timeout=20)
    r.raise_for_status()


# ── Template filters ──────────────────────────────────────────────────────────

@app.template_filter("fit_class")
def fit_class(score) -> str:
    score = int(score or 0)
    if score >= 85: return "fit-high"
    if score >= 70: return "fit-mid"
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
    if not s: return "—"
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).strftime("%b %d")
    except Exception:
        return s[:10]


@app.template_filter("days_ago")
def days_ago(s: str) -> str:
    if not s: return ""
    try:
        dt   = datetime.fromisoformat(s.replace("Z", "+00:00")).date()
        diff = (date.today() - dt).days
        if diff == 0:  return "today"
        if diff == 1:  return "yesterday"
        return f"{diff}d ago"
    except Exception:
        return ""


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def dashboard():
    data   = load_tracker()
    jobs   = data.get("jobs", [])
    active = [j for j in jobs if j.get("status") not in ("archived", "rejected", "withdrawn")]

    # Compact summary stats
    stats = {
        "total":        len([j for j in jobs if j.get("status") != "archived"]),
        "new":          sum(1 for j in active if j.get("status") == "new"),
        "applied":      sum(1 for j in active if j.get("status") in ("applied", "tailored", "reviewing")),
        "interviewing": sum(1 for j in active if j.get("status") == "interviewing"),
        "offers":       sum(1 for j in active if j.get("status") == "offer"),
    }

    # Fresh jobs: new status, ≥70% fit, last 14 days, sorted by fit desc
    two_weeks_ago = (date.today() - timedelta(days=14)).isoformat()
    fresh = sorted(
        [
            j for j in jobs
            if j.get("status") == "new"
            and j.get("fit_score", 0) >= 70
            and j.get("discovered_date", "")[:10] >= two_weeks_ago
        ],
        key=lambda j: j.get("fit_score", 0),
        reverse=True,
    )

    today_str    = date.today().isoformat()
    two_days_ago = (date.today() - timedelta(days=2)).isoformat()
    new_today    = sum(1 for j in fresh if j.get("discovered_date", "")[:10] >= today_str)
    new_2d       = sum(1 for j in fresh if j.get("discovered_date", "")[:10] >= two_days_ago)

    return render_template(
        "dashboard.html",
        stats=stats,
        fresh=fresh,
        new_today=new_today,
        new_2d=new_2d,
        last_scan=data.get("last_scan"),
        total_scans=data.get("total_scans", 0),
        github_token_set=bool(GITHUB_TOKEN),
    )


@app.route("/pipeline")
def pipeline_page():
    data  = load_tracker()
    jobs  = data.get("jobs", [])
    active_statuses = ("applied", "tailored", "reviewing", "interviewing", "offer")
    order = {"offer": 0, "interviewing": 1, "applied": 2, "tailored": 3, "reviewing": 4}

    pipeline = sorted(
        [j for j in jobs if j.get("status") in active_statuses],
        key=lambda j: (order.get(j.get("status", ""), 9), -(j.get("fit_score", 0))),
    )

    today_str = date.today().isoformat()
    follow_ups = [
        j for j in pipeline
        if j.get("follow_up_date") and j["follow_up_date"] <= today_str
        and j.get("status") not in ("offer",)
    ]

    return render_template(
        "pipeline.html",
        pipeline=pipeline,
        follow_ups=follow_ups,
        github_token_set=bool(GITHUB_TOKEN),
    )


@app.route("/jobs")
def jobs_page():
    data     = load_tracker()
    all_jobs = sorted(
        [j for j in data.get("jobs", []) if j.get("status") != "archived"],
        key=lambda j: j.get("fit_score", 0),
        reverse=True,
    )
    statuses = sorted({j.get("status", "new") for j in all_jobs})
    return render_template(
        "jobs.html",
        jobs=all_jobs,
        statuses=statuses,
        github_token_set=bool(GITHUB_TOKEN),
    )


# ── API endpoints ─────────────────────────────────────────────────────────────

@app.route("/api/update-job", methods=["POST"])
def update_job():
    """Update a job's status. Writes back to GitHub if GITHUB_TOKEN is set."""
    payload   = request.get_json(force=True) or {}
    job_id    = payload.get("job_id", "").strip()
    new_status = payload.get("status", "").strip()
    note      = payload.get("note", "").strip()

    valid_statuses = {
        "new", "reviewing", "tailored", "applied",
        "interviewing", "offer", "rejected", "withdrawn", "archived",
    }
    if not job_id or new_status not in valid_statuses:
        return jsonify({"ok": False, "error": "invalid params"}), 400

    data = load_tracker()
    job  = next((j for j in data.get("jobs", []) if j.get("id") == job_id), None)
    if not job:
        return jsonify({"ok": False, "error": "job not found"}), 404

    now = datetime.now(timezone.utc).isoformat()
    job["status"] = new_status
    if new_status == "applied" and not job.get("applied_date"):
        job["applied_date"] = now
    if note:
        ts = date.today().isoformat()
        existing = (job.get("notes") or "").strip()
        job["notes"] = f"{existing}\n[{ts}] {note}".strip()

    # Write back to GitHub
    github_ok = False
    if GITHUB_TOKEN:
        try:
            _github_commit_tracker(data)
            github_ok = True
        except Exception as e:
            app.logger.warning(f"GitHub commit failed: {e}")

    # Update local cache so the page reflects immediately
    _cache["data"] = data
    _cache["ts"]   = time.time()

    return jsonify({
        "ok":        True,
        "status":    new_status,
        "github_ok": github_ok,
    })


@app.route("/api/jobs")
def api_jobs():
    return jsonify(load_tracker().get("jobs", []))


@app.route("/api/stats")
def api_stats():
    data = load_tracker()
    jobs = data.get("jobs", [])
    by_status: dict = {}
    for j in jobs:
        s = j.get("status", "new")
        by_status[s] = by_status.get(s, 0) + 1
    avg_fit = sum(j.get("fit_score", 0) for j in jobs) / len(jobs) if jobs else 0
    return jsonify({
        "total":       len(jobs),
        "by_status":   by_status,
        "avg_fit":     round(avg_fit, 1),
        "last_scan":   data.get("last_scan"),
        "total_scans": data.get("total_scans", 0),
    })


@app.route("/api/refresh")
def api_refresh():
    _cache["ts"] = 0.0
    return redirect(url_for("dashboard"))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
