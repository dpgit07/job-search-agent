#!/usr/bin/env python3
"""
Daily job scanner — runs as a GitHub Actions cron job.

Uses Apify REST API to scrape LinkedIn jobs and Claude API to score each
posting against the candidate profile. Results are saved to
data/job_tracker.json which is committed back to the repo by the workflow.
The Flask dashboard on Render reads from that file via GitHub raw URL.

Usage:
    python scripts/scan_jobs.py             # full scan
    python scripts/scan_jobs.py --dry-run   # no Apify calls, tests scoring only
"""

import os
import sys
import json
import time
import hashlib
import argparse
import requests
from datetime import datetime, timezone, date, timedelta
from pathlib import Path

import anthropic

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
TRACKER_PATH  = ROOT / "data" / "job_tracker.json"
PROFILE_PATH  = ROOT / "data" / "profile.json"
COMPANIES_PATH = ROOT / "data" / "target_companies.json"

# ── Config ────────────────────────────────────────────────────────────────────
APIFY_TOKEN       = os.environ.get("APIFY_TOKEN", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Apify actor ID uses ~ separator in REST API (not /)
ACTOR_ID = "curious_coder~linkedin-jobs-scraper"

# Pre-built LinkedIn search URLs (actor requires URLs, not keyword strings).
# f_TPR=r86400  → posted in the last 24 hours
# f_E=4         → Senior level
# f_WT=2        → Remote only  (remove to include on-site/hybrid)
SEARCH_URLS = [
    # Senior Data Engineer — US, last 24h
    "https://www.linkedin.com/jobs/search/?keywords=Senior+Data+Engineer&location=United+States&f_TPR=r86400&f_E=4&position=1&pageNum=0",
    # Lead / Staff Data Engineer — US, last 24h
    "https://www.linkedin.com/jobs/search/?keywords=Lead+Data+Engineer&location=United+States&f_TPR=r86400&f_E=4&position=1&pageNum=0",
    "https://www.linkedin.com/jobs/search/?keywords=Staff+Data+Engineer&location=United+States&f_TPR=r86400&f_E=4&position=1&pageNum=0",
    # Spark/SQL focus — broader time window (past week) to catch more results
    "https://www.linkedin.com/jobs/search/?keywords=Data+Engineer+Spark+SQL&location=United+States&f_TPR=r604800&position=1&pageNum=0",
]

MAX_PER_URL   = 25   # LinkedIn jobs to scrape per URL
FIT_THRESHOLD = 70   # minimum fit % to add to tracker


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def save_json(path: Path, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def job_id(url: str) -> str:
    """Stable 12-char hash of the job URL used as primary key."""
    return hashlib.sha1(url.encode()).hexdigest()[:12]

def tier_for_company(company_name: str, company_tiers: dict) -> str:
    name_lower = company_name.lower()
    for tier, entries in company_tiers.items():
        for entry in entries:
            if entry["name"].lower() in name_lower or name_lower in entry["name"].lower():
                return tier
    return "tier_4"

def tier_score(tier: str) -> int:
    return {"tier_1": 10, "tier_2": 8, "tier_3": 6, "tier_4": 4}.get(tier, 4)


# ── Apify scraping ─────────────────────────────────────────────────────────────

def scrape_linkedin(search_url: str) -> list[dict]:
    """
    Run the Apify LinkedIn Jobs Scraper and return raw items.
    Actor input: list of LinkedIn search page URLs (not keyword strings).
    REST API uses ~ separator: curious_coder~linkedin-jobs-scraper
    """
    if not APIFY_TOKEN:
        print("  ⚠ APIFY_TOKEN not set — skipping Apify call")
        return []

    # Synchronous run — blocks until complete, returns dataset items directly.
    # Timeout 300s (5 min) to give the actor enough time.
    endpoint = (
        f"https://api.apify.com/v2/acts/{ACTOR_ID}"
        f"/run-sync-get-dataset-items"
        f"?token={APIFY_TOKEN}&timeout=300&memory=1024"
    )
    payload = {
        "urls":          [search_url],
        "count":         MAX_PER_URL,
        "scrapeCompany": False,   # skip extra company requests → faster & cheaper
    }

    label = search_url.split("keywords=")[1].split("&")[0].replace("+", " ")
    try:
        print(f"  Calling Apify: {label!r} …", end=" ", flush=True)
        r = requests.post(endpoint, json=payload, timeout=360)
        r.raise_for_status()
        items = r.json()
        print(f"{len(items)} results")
        return items
    except requests.HTTPError as e:
        print(f"HTTP {e.response.status_code} — {e.response.text[:200]}")
        return []
    except Exception as e:
        print(f"Error: {e}")
        return []


# ── Claude scoring ─────────────────────────────────────────────────────────────

def score_with_claude(job: dict, profile: dict, company_tiers: dict) -> dict:
    """
    Ask Claude Haiku to score the job against the candidate profile.
    Returns a dict with fit_score, fit_breakdown, matching/missing skills, etc.
    Falls back to rule-based scoring if the API is unavailable.
    """
    if not ANTHROPIC_API_KEY:
        return _rule_based_score(job, profile, company_tiers)

    tier  = tier_for_company(job.get("company", ""), company_tiers)
    t_score = tier_score(tier)

    prompt = f"""Score this job for a Senior Data Engineer. Return ONLY valid JSON — no markdown, no explanation.

CANDIDATE SKILLS
Expert:       {', '.join(profile['skills']['expert'])}
Advanced:     {', '.join(profile['skills']['advanced'])}
Intermediate: {', '.join(profile['skills']['intermediate'])}
Familiar:     {', '.join(profile['skills']['familiar'])}
Certifications: Snowflake SnowPro, Databricks DE Associate, Databricks Spark 3.0, GCP ACE, Azure AZ-900/DP-900, Airflow
Experience: {profile['experience_years']} years · M.Tech IIT Hyderabad (GPA 9.02) Big Data & Distributed Computing
Target salary: ${profile['target_salary_min']:,}+ base
Preferred locations: {', '.join(profile['preferred_locations'])}

JOB
Title:    {job.get('role', 'N/A')}
Company:  {job.get('company', 'N/A')} ({tier})
Location: {job.get('location', 'N/A')}
Salary:   {job.get('salary') or 'not listed'}
Description (truncated):
{str(job.get('description', ''))[:1500]}

WEIGHTS: skill_match/30, experience_match/20, salary_match/15, company_tier/10, location_match/10, growth_opportunity/10, visa_compatibility/5
company_tier is already determined: {t_score}/10

Return exactly:
{{
  "fit_score": <integer 0-100>,
  "fit_breakdown": {{
    "skill_match": <0-30>,
    "experience_match": <0-20>,
    "salary_match": <0-15>,
    "company_tier": {t_score},
    "location_match": <0-10>,
    "growth_opportunity": <0-10>,
    "visa_compatibility": <0-5>
  }},
  "key_skills_matching": ["max 5 skills"],
  "key_skills_missing": ["max 3 gaps"],
  "recommendation": "Apply|Maybe|Skip",
  "notes": "one sentence"
}}"""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        return json.loads(raw)
    except Exception as e:
        print(f"  Claude error ({e}) — using rule-based fallback")
        return _rule_based_score(job, profile, company_tiers)


def _rule_based_score(job: dict, profile: dict, company_tiers: dict) -> dict:
    """Fast keyword-based scorer — used when Claude API is unavailable."""
    # Build a composite text blob from all available text fields
    desc = " ".join([
        str(job.get("description", "")),
        str(job.get("role", "")),
        str(job.get("seniority_level", "")),
        str(job.get("industry", "")),
        str(job.get("employment_type", "")),
    ]).lower()

    # Skill match (0-30)
    all_skills = (
        [(s, 4) for s in profile["skills"]["expert"]] +
        [(s, 3) for s in profile["skills"]["advanced"]] +
        [(s, 2) for s in profile["skills"]["intermediate"]]
    )
    matching = [s for s, _ in all_skills if s.lower() in desc]
    skill_score = min(30, len(matching) * 4)

    # If description is completely empty, give a neutral mid-range skill score
    # (we know this is a DE role since we searched for it, not a 0-match)
    if not job.get("description") and not matching:
        skill_score = 12

    # Experience match (0-20)
    exp_score = 18 if any(x in desc for x in ["4+", "5+", "3+", "senior", "lead", "staff"]) else 14

    # Salary (0-15)
    sal = str(job.get("salary", "")).lower()
    if not sal or sal == "none":
        salary_score = 10  # unknown — neutral
    elif any(x in sal for x in ["140", "150", "160", "170", "180", "190", "200", "210", "220"]):
        salary_score = 15
    elif any(x in sal for x in ["120", "130"]):
        salary_score = 11
    else:
        salary_score = 8

    # Company tier (0-10)
    tier    = tier_for_company(job.get("company", ""), company_tiers)
    t_score = tier_score(tier)

    # Location (0-10)
    loc = str(job.get("location", "")).lower()
    if "remote" in loc:
        loc_score = 10
    elif any(x in loc for x in ["maryland", "virginia", " dc", "washington d"]):
        loc_score = 9
    elif any(x in loc for x in ["california", "new york", "seattle", "texas", "austin"]):
        loc_score = 7
    elif "united states" in loc or loc in ("", "unknown"):
        loc_score = 7   # US-wide or unknown → assume hybrid/remote possible
    else:
        loc_score = 5

    total = skill_score + exp_score + salary_score + t_score + loc_score + 8 + 5

    return {
        "fit_score": min(100, total),
        "fit_breakdown": {
            "skill_match":       skill_score,
            "experience_match":  exp_score,
            "salary_match":      salary_score,
            "company_tier":      t_score,
            "location_match":    loc_score,
            "growth_opportunity": 8,
            "visa_compatibility": 5,
        },
        "key_skills_matching": matching[:5],
        "key_skills_missing":  [],
        "recommendation": "Apply" if total >= 85 else ("Maybe" if total >= 70 else "Skip"),
        "notes": "Rule-based score — Claude API unavailable",
    }


# ── Normalise raw Apify item → tracker job dict ────────────────────────────────

def normalise(raw: dict) -> dict:
    """Map raw Apify LinkedIn scraper fields to our tracker schema.

    The curious_coder actor returns these relevant fields:
      url / jobUrl          — job posting URL
      title / jobTitle      — job title
      company / companyName — company name
      location              — location string
      salary / salaryRange  — salary (often empty on LinkedIn)
      postedAt              — ISO date string
      descriptionText       — plain-text description  ← prefer this
      description           — may be HTML or plain text
      seniorityLevel        — e.g. "Senior"
      employmentType        — e.g. "Full-time"
      industry              — e.g. "Technology"
    """
    url = (
        raw.get("url")
        or raw.get("jobUrl")
        or raw.get("link")
        or raw.get("applyUrl")
        or ""
    )

    # Prefer plain-text description; fall back to HTML version
    description_raw = (
        raw.get("descriptionText")
        or raw.get("description")
        or raw.get("jobDescription")
        or raw.get("descriptionHtml")
        or ""
    )
    description = str(description_raw)[:3000]

    return {
        "id":               job_id(url) if url else None,
        "company":          raw.get("company") or raw.get("companyName", "Unknown"),
        "role":             raw.get("title")   or raw.get("jobTitle",   "Unknown"),
        "location":         raw.get("location", "Unknown"),
        "salary":           raw.get("salary")  or raw.get("salaryRange", ""),
        "salary_min":       None,
        "salary_max":       None,
        "remote":           "yes" if "remote" in str(raw.get("location", "")).lower() else "unknown",
        "link":             url,
        "posted_date":      raw.get("postedAt") or raw.get("publishedAt", ""),
        "discovered_date":  datetime.now(timezone.utc).isoformat(),
        "status":           "new",
        "applied_date":     None,
        "resume_version":   None,
        "cover_letter":     None,
        "follow_up_date":   None,
        "contacts":         [],
        "interview_dates":  [],
        "notes":            "",
        "seniority_level":  raw.get("seniorityLevel", ""),
        "employment_type":  raw.get("employmentType", ""),
        "industry":         raw.get("industry", ""),
        "description":      description,
        "description_snippet": description[:250],
    }


# ── Archive helpers ────────────────────────────────────────────────────────────

def auto_archive_stale(tracker: dict) -> int:
    """Mark stale low-fit 'new' jobs as 'archived' — runs at start of each scan.

    A job is archived if it is:
      - status == "new" (not yet acted on)
      - fit_score < 70 (below threshold)
      - discovered_date older than 30 days
    """
    cutoff = (date.today() - timedelta(days=30)).isoformat()
    count = 0
    for job in tracker.get("jobs", []):
        if (
            job.get("status") == "new"
            and job.get("fit_score", 100) < 70
            and job.get("discovered_date", "")[:10] < cutoff
        ):
            job["status"] = "archived"
            count += 1
    return count


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Scan LinkedIn jobs via Apify + Claude")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Skip Apify calls; test scoring pipeline only"
    )
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"Job Scanner  ·  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    if args.dry_run:
        print("  MODE: DRY RUN — no Apify calls")
    print(f"{'='*60}\n")

    profile       = load_json(PROFILE_PATH)
    tracker       = load_json(TRACKER_PATH)
    company_tiers = load_json(COMPANIES_PATH)

    # Auto-archive stale low-fit jobs before scanning new ones
    archived_count = auto_archive_stale(tracker)
    if archived_count:
        print(f"Archived {archived_count} stale jobs (>30 days old, fit <70%)\n")

    existing_ids = {j["id"] for j in tracker.get("jobs", []) if j.get("id")}

    added     = []
    skipped   = 0
    dup_count = 0
    total_raw = 0

    for idx, search_url in enumerate(SEARCH_URLS):
        label = search_url.split("keywords=")[1].split("&")[0].replace("+", " ")
        print(f"[URL {idx+1}/{len(SEARCH_URLS)}] {label}")

        if args.dry_run:
            # Inject one fake job so the scoring pipeline can be tested
            raw_items = [{
                "title":       "Senior Data Engineer (Dry Run)",
                "company":     "Databricks",
                "location":    "Remote, United States",
                "jobUrl":      f"https://example.com/job/{label.replace(' ','-').lower()}-{idx}",
                "description": (
                    "We're looking for a Senior Data Engineer proficient in Spark, "
                    "Scala, Python, SQL, Airflow, and Delta Lake. 4+ years experience."
                ),
            }]
        else:
            raw_items = scrape_linkedin(search_url)

        total_raw += len(raw_items)

        for raw in raw_items:
            job = normalise(raw)

            if not job["id"] or not job["link"]:
                continue

            if job["id"] in existing_ids:
                dup_count += 1
                continue

            # Score
            scoring = score_with_claude(job, profile, company_tiers)
            job.update({
                "fit_score":          scoring.get("fit_score", 0),
                "fit_breakdown":      scoring.get("fit_breakdown", {}),
                "key_skills_matching": scoring.get("key_skills_matching", []),
                "key_skills_missing":  scoring.get("key_skills_missing", []),
                "recommendation":     scoring.get("recommendation", "Maybe"),
                "scoring_notes":      scoring.get("notes", ""),
            })

            # Remove raw description before saving (saves space)
            job.pop("description", None)

            if job["fit_score"] >= FIT_THRESHOLD:
                added.append(job)
                existing_ids.add(job["id"])
                icon = "🔥" if job["fit_score"] >= 85 else "✓ "
                print(
                    f"  {icon} {job['fit_score']:>3}%  {job['recommendation']:<6}  "
                    f"{job['company']:<22}  {job['role']}"
                )
            else:
                skipped += 1
                print(f"  ✗   {job['fit_score']:>3}%  Skip     {job['company']:<22}  {job['role']}")

    # Persist
    tracker.setdefault("jobs", []).extend(added)
    tracker["last_scan"]   = datetime.now(timezone.utc).isoformat()
    tracker["total_scans"] = tracker.get("total_scans", 0) + 1

    save_json(TRACKER_PATH, tracker)

    # Summary
    high = [j for j in added if j["fit_score"] >= 85]
    print(f"\n{'='*60}")
    print(f"SCAN COMPLETE")
    print(f"  Scraped   : {total_raw:>4}  jobs")
    print(f"  Duplicates: {dup_count:>4}  already tracked")
    print(f"  Added     : {len(added):>4}  new (≥{FIT_THRESHOLD}% fit)")
    print(f"  Skipped   : {skipped:>4}  below threshold")
    print(f"  🔥 High priority (≥85%): {len(high)}")
    print(f"  Total tracked: {len(tracker['jobs'])}")
    print(f"{'='*60}\n")

    if high:
        print("HIGH PRIORITY — apply soon:")
        for j in sorted(high, key=lambda x: x["fit_score"], reverse=True):
            print(f"  {j['fit_score']}%  {j['company']}  —  {j['role']}")
            print(f"         {j['link']}")


if __name__ == "__main__":
    main()
