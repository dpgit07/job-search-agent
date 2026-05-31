# 🤖 Job Search Automation Agent

> An AI-powered job search agent built on **Claude Code** — automates scanning, resume tailoring, cover letter writing, interview prep, and application tracking for Senior Data Engineer roles in the USA.

**Author:** Dharmendra Kumar Prajapati  
**Stack:** Claude Code · Apify MCP · Claude Subagents · Slash Commands · Hooks

---

## What This Does

| Module | What It Automates |
|--------|-------------------|
| **Job Scanner** | Scrapes LinkedIn, Indeed & company career pages daily for matching roles |
| **Resume Tailor** | Generates ATS-optimized resume variants per job description |
| **Skill Gap Analyzer** | Compares your profile vs. market trends, ranks upskilling priorities |
| **Application Tracker** | Maintains a structured JSON tracker of all applications & follow-ups |
| **Interview Prep** | Generates company-specific technical + behavioral prep packages |
| **Networking Assistant** | Drafts personalized recruiter outreach, referral requests, thank-you notes |
| **Cover Letter Writer** | Writes tailored, ATS-friendly cover letters (never generic) |

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                CLAUDE CODE (Main Agent)                  │
│                      CLAUDE.md                           │
│           (Profile · Rules · Preferences)                │
├──────────────┬──────────────┬────────────┬──────────────┤
│  Subagent:   │  Subagent:   │ Subagent:  │  Subagent:   │
│  job-scanner │resume-tailor │ skill-gap  │interview-prep│
├──────────────┴──────────────┴────────────┴──────────────┤
│                     MCP SERVERS                          │
│  Apify (scrape) · Gmail · Google Sheets · GitHub         │
│  Google Drive · Google Calendar · Filesystem             │
├─────────────────────────────────────────────────────────┤
│  HOOKS: SessionStart → load state · Stop → save memory  │
└─────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
job-search-agent/
├── CLAUDE.md                        # Core agent instructions & candidate profile
├── README.md
├── .gitignore
│
├── resume/
│   ├── master_resume.md             # Your base resume (edit this)
│   └── tailored/                    # Auto-generated tailored versions
│
├── data/
│   ├── profile.json                 # Your skills, experience, preferences
│   ├── job_tracker.json             # Application database (auto-updated)
│   ├── skill_market_trends.json     # Cached market analysis
│   ├── target_companies.json        # Tier 1–4 target companies
│   └── interview_notes/             # Company-specific prep materials
│
├── output/
│   ├── reports/                     # Daily/weekly digest reports
│   ├── cover_letters/               # Generated cover letters
│   └── tailored_resumes/            # Final tailored resume files
│
└── .claude/
    ├── settings.json                # Permissions, hooks config
    ├── memory.md                    # Persistent session memory
    ├── agents/                      # 6 subagent definitions
    │   ├── job-scanner.md
    │   ├── resume-tailor.md
    │   ├── skill-gap-analyzer.md
    │   ├── interview-prep.md
    │   ├── networking-assistant.md
    │   └── cover-letter-writer.md
    └── commands/                    # 8 slash commands
        ├── scan.md       → /scan
        ├── apply.md      → /apply
        ├── tailor.md     → /tailor
        ├── prep.md       → /prep
        ├── status.md     → /status
        ├── trends.md     → /trends
        ├── outreach.md   → /outreach
        └── daily.md      → /daily
```

---

## Slash Commands

| Command | Usage | What It Does |
|---------|-------|--------------|
| `/daily` | `/daily` | Full morning routine: scan → tailor → status → digest |
| `/scan` | `/scan` | Find new matching jobs (70%+ fit) across all sources |
| `/apply` | `/apply Google` | Tailor resume + cover letter for a job, then confirm to submit |
| `/tailor` | `/tailor Amazon` | Generate ATS-optimized tailored resume for a JD |
| `/prep` | `/prep Meta` | Generate interview prep package (technical + behavioral) |
| `/status` | `/status` | Full application dashboard with follow-up alerts |
| `/trends` | `/trends` | Market skill demand analysis + your gap report |
| `/outreach` | `/outreach recruiter Databricks` | Draft personalized networking message |

---

## Setup

### Prerequisites
- [Claude Code](https://claude.ai/code) installed (`npm install -g @anthropic-ai/claude-code`)
- Node.js 18+ and Python 3.10+
- An [Apify](https://apify.com) account (free tier: 100 scrapes/month)
- A GitHub account

### Step 1 — Clone & Enter the Project
```bash
git clone https://github.com/dpgit07/job-search-agent.git
cd job-search-agent
```

### Step 2 — Update Your Profile
Edit these two files with your personal details:

**`CLAUDE.md`** — update:
```
- Visa Status: [H1B / GC / Citizen]
- LinkedIn: [your LinkedIn URL]
```

**`data/profile.json`** — update:
```json
"visa_status": "H1B",
"linkedin_url": "https://linkedin.com/in/yourprofile"
```

**`resume/master_resume.md`** — paste in your full resume content.

### Step 3 — Install MCP Servers
```bash
# Minimum required — job scraping
claude mcp add apify \
  -e APIFY_TOKEN=your_apify_token \
  -- npx -y @anthropic-ai/apify-mcp-server

# Local file access
claude mcp add filesystem \
  -- npx -y @modelcontextprotocol/server-filesystem $(pwd)

# Optional — GitHub version control
claude mcp add github \
  -e GITHUB_PERSONAL_ACCESS_TOKEN=your_github_token \
  -- npx -y @modelcontextprotocol/server-github

# Optional — Gmail, Calendar, Sheets (requires Google OAuth setup)
claude mcp add gmail -- npx -y @anthropic-ai/gmail-mcp-server
claude mcp add google-sheets -- npx -y @anthropic-ai/google-sheets-mcp-server
claude mcp add google-calendar -- npx -y @anthropic-ai/google-calendar-mcp-server
```

Get your Apify token from: https://console.apify.com/account/integrations

### Step 4 — Launch
```bash
claude
# Inside Claude Code:
/daily
```

---

## Daily Workflow

```
Morning:
  /daily              → Full scan + digest + action list

Per application:
  /apply {company}    → Tailored resume + cover letter (requires your OK before submitting)
  /outreach recruiter {company}  → Draft recruiter message

Before interviews:
  /prep {company}     → Technical + behavioral prep package

Weekly:
  /trends             → Skill gap report + market intelligence
  /status             → Full pipeline dashboard
```

---

## Fit Scoring

Each job is scored 0–100 using weighted criteria:

| Criterion | Weight |
|-----------|--------|
| Technical skill match | 30% |
| Experience level match | 20% |
| Salary / compensation | 15% |
| Company tier (1–4) | 10% |
| Location / remote flexibility | 10% |
| Growth opportunity | 10% |
| Visa compatibility | 5% |

Jobs scoring **≥ 85%** are flagged HIGH PRIORITY and get automatic resume/cover letter drafts.  
Jobs scoring **< 70%** are filtered out.

---

## Safety & Privacy

- **Never auto-submits** — Every application requires explicit `yes` confirmation
- **Data stays local** — Profile and tracker live in `data/` on your machine
- **No secrets in repo** — `.gitignore` excludes all tokens, credentials, and OAuth files
- **Scraping via Apify** — Uses Apify's authorized infrastructure (rate-limit safe)

---

## Target Companies

| Tier | Companies |
|------|-----------|
| **Tier 1** | LinkedIn, Meta, Google, Apple, Amazon, Microsoft, Netflix |
| **Tier 2** | Databricks, Snowflake, Capital One, Airbnb, Uber, Stripe, Disney |
| **Tier 3** | T-Mobile, Salesforce, Adobe, Oracle, Walmart, JPMorgan, Goldman Sachs |
| **Tier 4** | Any company · matching role · $140K+ base · good culture |

---

## MCP Servers Reference

| Server | Purpose | Required? |
|--------|---------|-----------|
| `apify` | Job scraping from LinkedIn, Indeed, company sites | **Yes** |
| `filesystem` | Read/write local project files | **Yes** |
| `github` | Resume version control | Recommended |
| `gmail` | Email applications, track responses | Optional |
| `google-sheets` | Spreadsheet application tracker | Optional |
| `google-calendar` | Schedule interviews, set reminders | Optional |

---

## Contributing

This is a personal job search automation tool. Fork it and adapt the `CLAUDE.md` candidate profile section to your own background.

---

*Built with [Claude Code](https://claude.ai/code) · Powered by [Apify](https://apify.com) · v1.0.0*
