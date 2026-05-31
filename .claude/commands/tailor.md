Generate a tailored resume for a specific job description. Usage: /tailor {job_url_or_company}

Steps:
1. Fetch the job description (from tracker or provided URL)
2. Invoke resume-tailor subagent
3. Show a diff of changes from master resume highlighting:
   - Sections reordered
   - Keywords added for ATS
   - Metrics prioritized for this JD
4. Save to output/tailored_resumes/
5. Ask if you'd like a cover letter generated as well
