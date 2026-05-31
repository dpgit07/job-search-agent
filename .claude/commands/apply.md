Prepare application materials for a specific job. Usage: /apply {company_name} or /apply {job_tracker_id}

Steps:
1. Look up the job in data/job_tracker.json
2. Invoke resume-tailor subagent to create a tailored resume
3. Invoke cover-letter-writer subagent to create a cover letter
4. Present both for human review
5. After approval, update job_tracker.json status to "applied"
6. If Gmail MCP is connected, draft the application email
7. Set a 1-week follow-up reminder in the tracker

IMPORTANT: NEVER submit an application without explicit human confirmation.
Always present the tailored materials and ask: "Ready to submit? (yes/no)"
