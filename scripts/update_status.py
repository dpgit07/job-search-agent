#!/usr/bin/env python3
"""
Manual job application status updater.

Use this after you apply, hear back, or get a rejection.
Changes are saved to data/job_tracker.json; run with --push to commit & push
so the Render dashboard picks up the update within 5 minutes.

Examples:
    python scripts/update_status.py --list
    python scripts/update_status.py --list --status applied
    python scripts/update_status.py --company Meta --status applied
    python scripts/update_status.py --company Meta --status applied --note "Applied via LinkedIn"
    python scripts/update_status.py --company Databricks --status interviewing
    python scripts/update_status.py --company Stripe --status rejected --note "No feedback"
    python scripts/update_status.py --id abc123def456 --status offer
    python scripts/update_status.py --archive-old          # archive stale low-fit jobs now
    python scripts/update_status.py --company Meta --status applied --push
"""

import os
import sys
import json
import subprocess
import argparse
from datetime import datetime, timezone, date, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
TRACKER_PATH = ROOT / "data" / "job_tracker.json"

VALID_STATUSES = [
    "new", "reviewing", "tailored", "applied",
    "interviewing", "offer", "rejected", "withdrawn", "archived",
]

STATUS_ORDER = {
    "offer": 0, "interviewing": 1, "applied": 2,
    "tailored": 3, "reviewing": 4, "new": 5,
    "rejected": 6, "withdrawn": 7, "archived": 8,
}


def load_tracker() -> dict:
    with open(TRACKER_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_tracker(tracker: dict) -> None:
    with open(TRACKER_PATH, "w", encoding="utf-8") as f:
        json.dump(tracker, f, indent=2, ensure_ascii=False)


def fmt(s: str) -> str:
    if not s:
        return "—"
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).strftime("%b %d")
    except Exception:
        return s[:10]


def list_jobs(jobs: list, status_filter: str | None = None) -> None:
    visible = [j for j in jobs if not status_filter or j.get("status") == status_filter]
    visible = sorted(visible, key=lambda j: (
        STATUS_ORDER.get(j.get("status", ""), 9), -(j.get("fit_score", 0))
    ))
    if not visible:
        print("No jobs found.")
        return
    print(f"\n{'ID':>12}  {'Fit':>4}  {'Status':<14}  {'Company':<22}  {'Role':<38}  Found")
    print("─" * 100)
    for j in visible:
        print(
            f"  {j.get('id', '?'):<12}  {j.get('fit_score', 0):>3}%  "
            f"{j.get('status', 'new'):<14}  {j.get('company', '?'):<22}  "
            f"{j.get('role', '?')[:38]:<38}  {fmt(j.get('discovered_date', ''))}"
        )
    print(f"\n  Total: {len(visible)}\n")


def find_jobs(jobs: list, company: str = "", job_id: str = "") -> list:
    if job_id:
        return [j for j in jobs if j.get("id", "").startswith(job_id.lower())]
    if company:
        cl = company.lower()
        return [j for j in jobs if cl in j.get("company", "").lower()]
    return []


def update_jobs(matches: list, new_status: str, note: str = "") -> list:
    now = datetime.now(timezone.utc).isoformat()
    results = []
    for j in matches:
        old = j.get("status", "new")
        j["status"] = new_status
        if new_status == "applied" and not j.get("applied_date"):
            j["applied_date"] = now
        if note:
            ts = date.today().isoformat()
            existing = j.get("notes", "") or ""
            j["notes"] = f"{existing}\n[{ts}] {note}".strip()
        results.append((j, old, new_status))
    return results


def archive_old(jobs: list, dry_run: bool = False) -> int:
    cutoff = (date.today() - timedelta(days=30)).isoformat()
    count = 0
    for j in jobs:
        if (
            j.get("status") == "new"
            and j.get("fit_score", 100) < 70
            and j.get("discovered_date", "")[:10] < cutoff
        ):
            if not dry_run:
                j["status"] = "archived"
            count += 1
    return count


def git_push() -> bool:
    try:
        subprocess.run(["git", "add", "data/job_tracker.json"], cwd=ROOT, check=True)
        diff = subprocess.run(
            ["git", "diff", "--cached", "--quiet"], cwd=ROOT
        )
        if diff.returncode == 0:
            print("No changes to commit — tracker already up to date.")
            return True
        subprocess.run(
            ["git", "commit", "-m", f"chore: update job statuses {date.today()}"],
            cwd=ROOT, check=True,
        )
        subprocess.run(["git", "pull", "--rebase", "origin", "main"], cwd=ROOT, check=True)
        subprocess.run(["git", "push"], cwd=ROOT, check=True)
        print("Pushed. Dashboard refreshes within 5 minutes.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Git error: {e}")
        return False


def main():
    ap = argparse.ArgumentParser(
        description="Update job application statuses manually",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--list", action="store_true", help="List jobs (optionally filtered by --status)")
    ap.add_argument("--status", help="Status to set (or filter with --list)")
    ap.add_argument("--company", default="", help="Company name — partial match, case-insensitive")
    ap.add_argument("--id", default="", dest="job_id", help="Job ID prefix (from --list output)")
    ap.add_argument("--note", default="", help="Append a timestamped note to matched jobs")
    ap.add_argument("--archive-old", action="store_true",
                    help="Archive jobs older than 30 days with fit < 70%% and status 'new'")
    ap.add_argument("--push", action="store_true",
                    help="Commit and push tracker to GitHub after changes")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would change — do not save")
    args = ap.parse_args()

    tracker = load_tracker()
    jobs = tracker.get("jobs", [])

    # ── List mode ──────────────────────────────────────────────────────────────
    if args.list:
        list_jobs(jobs, args.status or None)
        return

    # ── Archive old ────────────────────────────────────────────────────────────
    if args.archive_old:
        count = archive_old(jobs, dry_run=args.dry_run)
        if args.dry_run:
            print(f"[dry-run] Would archive {count} stale jobs (>30d old, fit <70%).")
        else:
            save_tracker(tracker)
            print(f"Archived {count} stale jobs.")
            if args.push and count:
                git_push()
        return

    # ── Status update mode ─────────────────────────────────────────────────────
    if not args.status:
        print("Error: --status is required to update jobs.\n")
        print(f"Valid statuses: {', '.join(VALID_STATUSES)}\n")
        ap.print_usage()
        sys.exit(1)

    if args.status not in VALID_STATUSES:
        print(f"Invalid status '{args.status}'.")
        print(f"Valid statuses: {', '.join(VALID_STATUSES)}")
        sys.exit(1)

    if not args.company and not args.job_id:
        print("Error: provide --company or --id to identify the job.\n")
        ap.print_usage()
        sys.exit(1)

    matches = find_jobs(jobs, args.company, args.job_id)
    if not matches:
        q = args.company or args.job_id
        print(f"No jobs found matching '{q}'.")
        print("Run --list to see all tracked jobs.")
        sys.exit(1)

    print(f"\nMatched {len(matches)} job(s):")
    for j in matches:
        print(f"  {j.get('id')}  {j.get('fit_score')}%  "
              f"[{j.get('status')}]  {j.get('company')}  —  {j.get('role')}")

    if args.dry_run:
        print(f"\n[dry-run] Would set status → '{args.status}'" +
              (f"  note: '{args.note}'" if args.note else ""))
        return

    results = update_jobs(matches, args.status, args.note)
    save_tracker(tracker)

    print(f"\nUpdated {len(results)} job(s):")
    for j, old, new in results:
        print(f"  {j.get('company')}  {old} → {new}")
        if args.note:
            print(f"    note: {args.note}")

    if args.push:
        print()
        git_push()
    else:
        print(f"\nChanges saved locally.")
        print(f"To push: python scripts/update_status.py --company \"{args.company}\" "
              f"--status {args.status} --push")
        print(f"Or:      git add data/job_tracker.json && git push")


if __name__ == "__main__":
    main()
