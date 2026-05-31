Run the job scanner subagent to find new job postings matching the candidate profile.

Steps:
1. Invoke the job-scanner subagent
2. Search LinkedIn, Indeed, and target company career pages for new postings
3. Score each job on fit percentage
4. Update data/job_tracker.json with new entries
5. Return a summary table of new jobs found (70%+ fit only)
6. Highlight any 85%+ fit jobs as "HIGH PRIORITY — apply soon"

Use Apify actors to scrape:
- curious_coder/linkedin-jobs-scraper for LinkedIn
- apify/rag-web-browser for company career pages

Search queries:
- "Senior Data Engineer" United States
- "Lead Data Engineer" United States
- "Staff Data Engineer" United States
- "Data Engineer Spark" United States
