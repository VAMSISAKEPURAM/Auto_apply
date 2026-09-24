# 🚀 Naukri Job-Search & Apply Agent

An intelligent, anti-bot-aware automation agent designed for **Naukri.com**. It searches for relevant listings, ranks job fit against your resume using **Groq LLM (Llama 3.3 70B)**, stages applications, answers screening questions, and pauses at an interactive **Human Approval Checkpoint** before any irreversible submission.

---

## 🛡️ Anti-Detection Architecture & Safety Measures

1. **Human Login with Session Persistence**: Never scripts credentials, OTPs, or CAPTCHAs. Logs in once interactively in a visible browser and persists cookies/tokens to `data/session.json`.
2. **Playwright Stealth**: Uses randomized user agents, realistic viewports, navigator property overrides, and smooth scrolling.
3. **Throttled Interactions**: Random jitter delays (3.5s – 7.5s) between pagination and application requests.
4. **Human Approval Checkpoint**: Displays fit score, justification, answered screening questions, and visual form screenshots before submitting.
5. **Dry-Run by Default**: Forms are filled and verified without submitting until you choose to go live.

---

## 📁 Project Structure

```
Job_search_apply_agent/
├── config/
│   ├── settings.yaml          # Search terms, filters, delay intervals
│   └── resume.txt             # Plain-text resume for LLM fit scoring
├── data/
│   ├── agent.db               # SQLite database
│   └── session.json           # Authenticated session storage state
├── screenshots/               # Visual screenshots of staged applications
├── logs/                      # Rotating date-stamped execution logs
├── src/
│   ├── __init__.py
│   ├── db.py                  # Database schema & lifecycle state queries
│   ├── auth.py                # Session persistence & profile validation
│   ├── scraper.py             # Search URL builder & job card parser
│   ├── ranker.py              # Groq LLM relevance & fit scoring engine
│   ├── applier.py             # Apply flow, screening Q&A solver & checkpoint
│   ├── utils.py               # Anti-detection helpers, jitter delays, URL cleaner
│   └── main.py                # Command-line interface orchestration
├── tests/
│   └── test_agent.py          # Automated verification tests
├── requirements.txt
├── .env.example
└── .gitignore
```

---

## ⚡ Quick Start & Deployment

### 1. Run 24/7 Fully Automated Daemon (Every 1 Hour, Top 20 Apps + Excel Export)
Simply double-click:
👉 **[`start_auto_agent.bat`](file:///d:/D_Drive/Job_search_apply_agent/start_auto_agent.bat)**

Or via terminal:
```powershell
.\venv\Scripts\python -m src.main schedule
```
- **Fires automatically every 1 hour**.
- **Scrapes new jobs**, evaluates fit with Groq LLM, and **applies to top 20 qualified jobs** hands-free.
- **Automatically generates formatted Excel reports** at [`reports/applied_jobs_latest.xlsx`](file:///d:/D_Drive/Job_search_apply_agent/reports/applied_jobs_latest.xlsx).

---

### 2. Export Applied Jobs to Excel Anytime
```powershell
.\venv\Scripts\python -m src.main export
```
Exports a spreadsheet with:
- **Applied Jobs Sheet**: Job Title, Employer, Location, Experience, Fit Score, Justification, Applied Date & Time, Direct URL, and Screening Q&A.
- **All Tracked Jobs Sheet**: Full catalog of scraped and evaluated listings.

---

### 3. Step-by-Step Individual Commands
```powershell
# Authenticate session (one-time manual login)
.\venv\Scripts\python -m src.main login

# Scrape jobs
.\venv\Scripts\python -m src.main scrape

# Score fit with Groq LLM
.\venv\Scripts\python -m src.main rank

# Apply to top qualified jobs
.\venv\Scripts\python -m src.main apply

# View applied list in terminal
.\venv\Scripts\python -m src.main applied

# View summary counts
.\venv\Scripts\python -m src.main summary
```

---

## 🧪 Testing & Selector Health Check

- Run automated test suite:
  ```powershell
  .\venv\Scripts\python -m unittest tests/test_agent.py
  ```
- Run live selector health check:
  ```powershell
  .\venv\Scripts\python -m src.main health
  ```
