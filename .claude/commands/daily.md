Run the complete daily job search routine.

Execute these steps in order:

1. Run /scan — Find new matching jobs (70%+ fit)
2. For any 85%+ fit jobs, auto-run /tailor to prepare resume drafts
3. Run /status — Show current application dashboard
4. Check for overdue follow-ups and surface them
5. Generate daily digest report and save to output/reports/daily_{date}.md
6. Present the digest with recommended actions for today

## Daily Digest Format

```
## Daily Job Search Digest — {date}

### New Jobs Found: X
### High Priority (85%+): X jobs (listed below)
### Applications Pending: X
### Follow-ups Due: X

### High Priority Jobs Today:
| Company | Role | Fit% | Salary | Link |
|---------|------|------|--------|------|

### Today's Recommended Actions:
1. Apply to {company} — 92% fit, {role}
2. Follow up with {company} — 7 days since application
3. Prep for {company} interview on {date}
4. Learn {skill} — appears in 70% of recent JDs

### This Week's Pipeline Health:
- X applications in flight
- X interviews scheduled
- X offers pending
```
