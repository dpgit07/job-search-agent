#!/usr/bin/env python3
"""
Standalone fit re-scorer.

Run this to re-score all existing jobs in the tracker without
running a new Apify scrape — useful after updating your profile
or after Claude was unavailable during the original scan.

Usage:
    python scripts/analyze_fit.py              # re-score all jobs
    python scripts/analyze_fit.py --min 70     # only re-score below 70%
    python scripts/analyze_fit.py --company Databricks
"""

import os
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone

import anthropic

ROOT = Path(__file__).parent.parent
TRACKER_PATH   = ROOT / "data" / "job_tracker.json"
PROFILE_PATH   = ROOT / "data" / "profile.json"
COMPANIES_PATH = ROOT / "data" / "target_companies.json"

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


def load_json(p: Path) -> dict:
    with open(p) as f:
        return json.load(f)


def save_json(p: Path, d: dict):
    with open(p, "w") as f:
        json.dump(d, f, indent=2)


def tier_for_company(name: str, tiers: dict) -> str:
    nl = name.lower()
    for tier, entries in tiers.items():
        for e in entries:
            if e["name"].lower() in nl or nl in e["name"].lower():
                return tier
    return "tier_4"


def rescore(job: dict, profile: dict, tiers: dict) -> dict:
    if not ANTHROPIC_API_KEY:
        print("  ANTHROPIC_API_KEY not set — cannot rescore")
        return {}

    tier  = tier_for_company(job.get("company", ""), tiers)
    t_score = {"tier_1": 10, "tier_2": 8, "tier_3": 6, "tier_4": 4}.get(tier, 4)

    prompt = f"""Re-score this already-tracked job for a Senior Data Engineer. Return ONLY valid JSON.

CANDIDATE SKILLS
Expert:       {', '.join(profile['skills']['expert'])}
Advanced:     {', '.join(profile['skills']['advanced'])}
Intermediate: {', '.join(profile['skills']['intermediate'])}
Experience: {profile['experience_years']} yrs · M.Tech IIT Hyderabad (GPA 9.02)
Certifications: Snowflake SnowPro, Databricks DE Associate, Databricks Spark 3.0, GCP ACE, Azure AZ-900/DP-900
Target salary: ${profile['target_salary_min']:,}+
Preferred: {', '.join(profile['preferred_locations'])}

JOB
Title:    {job.get('role', 'N/A')}
Company:  {job.get('company', 'N/A')} ({tier})
Location: {job.get('location', 'N/A')}
Salary:   {job.get('salary') or 'not listed'}
Skills required: {', '.join(job.get('key_skills_required', []) or [])}
Notes from last score: {job.get('scoring_notes', 'n/a')}
company_tier is already determined: {t_score}/10

Return:
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
  "key_skills_matching": ["max 5"],
  "key_skills_missing": ["max 3"],
  "recommendation": "Apply|Maybe|Skip",
  "notes": "one sentence"
}}"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model="claude-3-5-haiku-20241022",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1].lstrip("json").strip()
    return json.loads(raw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min",     type=int, default=0,  help="Only rescore jobs with fit_score below this")
    ap.add_argument("--company", type=str, default="", help="Only rescore jobs at this company")
    ap.add_argument("--status",  type=str, default="", help="Only rescore jobs with this status")
    args = ap.parse_args()

    profile = load_json(PROFILE_PATH)
    tracker = load_json(TRACKER_PATH)
    tiers   = load_json(COMPANIES_PATH)

    jobs = tracker.get("jobs", [])
    targets = [
        j for j in jobs
        if (not args.min     or j.get("fit_score", 100) < args.min)
        and (not args.company or args.company.lower() in j.get("company", "").lower())
        and (not args.status  or j.get("status") == args.status)
    ]

    print(f"Re-scoring {len(targets)} of {len(jobs)} jobs …\n")
    changed = 0

    for j in targets:
        print(f"  {j.get('company'):<22}  {j.get('role')}")
        try:
            scoring = rescore(j, profile, tiers)
            if scoring:
                old = j.get("fit_score", 0)
                j.update({
                    "fit_score":           scoring["fit_score"],
                    "fit_breakdown":       scoring["fit_breakdown"],
                    "key_skills_matching": scoring["key_skills_matching"],
                    "key_skills_missing":  scoring["key_skills_missing"],
                    "recommendation":      scoring["recommendation"],
                    "scoring_notes":       scoring["notes"],
                    "rescored_at":         datetime.now(timezone.utc).isoformat(),
                })
                delta = scoring["fit_score"] - old
                sign = "+" if delta >= 0 else ""
                print(f"    {old}% → {scoring['fit_score']}%  ({sign}{delta})  {scoring['recommendation']}")
                changed += 1
        except Exception as e:
            print(f"    Error: {e}")

    save_json(TRACKER_PATH, tracker)
    print(f"\nDone — {changed} jobs rescored and saved.")


if __name__ == "__main__":
    main()
