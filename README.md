# 🚀 Multi-Platform Job-Search & Apply Agent

An intelligent, anti-bot-aware automation agent supporting **6 major hiring platforms**:
- **Naukri.com**
- **LinkedIn** (Easy Apply)
- **Foundit** (Monster India)
- **Indeed** (India)
- **Shine.com**
- **Instahyre**

The agent searches for relevant listings, filters on experience and city, ranks job fit against your resume using **Groq LLM**, stages applications, answers recruiter screening questions, records applications atomically to an Excel tracker, and can run hands-free in a 24/7 background scheduler.

---

## 🛡️ Anti-Detection Architecture & Safety Measures

1. **Human Login with Session Persistence**: Never scripts credentials, OTPs, or CAPTCHAs. Logs in once interactively in a visible browser and persists cookies/tokens to `data/sessions/<platform>.json` and `profiles/<platform>/`.
2. **Playwright Stealth**: Uses randomized user agents, realistic viewports, navigator property overrides, and smooth human-like scrolling.
3. **Throttled Interactions**: Random jitter delays (3.5s – 7.5s) between pagination and application requests.
4. **Human Approval Checkpoint / Dry-Run**: Displays fit score, justification, answered screening questions, and visual form screenshots before submitting.
5. **Real-time Atomic Excel Logging**: Writes each application status immediately to `reports/applied_jobs_latest.xlsx` with deduplication across `(Site, Job URL)`.

---

## 📁 Project Structure

```
Job_search_apply_agent/
├── config/
│   ├── settings.yaml          # Search terms, platforms, filters, delay intervals
│   └── resume.txt             # Plain-text resume for LLM fit scoring
├── data/
│   ├── agent.db               # SQLite database tracking jobs & application statuses
│   └── sessions/              # Platform session storage states (.json)
├── profiles/                  # Dedicated Chromium browser profile folders per site
├── reports/                   # Excel application workbooks (applied_jobs_latest.xlsx)
├── screenshots/               # Visual screenshots of staged applications
├── logs/                      # Rotating date-stamped execution logs
├── src/
│   ├── __init__.py
│   ├── db.py                  # Database schema, migrations & deduplication queries
│   ├── auth.py                # Platform session persistence & profile validation
│   ├── filters.py             # Experience parsing, city alias matcher & URL builders
│   ├── platforms/             # Platform adapter modules
│   │   ├── base.py            # JobPlatform abstract base class
│   │   ├── naukri.py          # Naukri adapter & chatbot solver
│   │   ├── linkedin.py        # LinkedIn Easy Apply adapter & checkpoint guards
│   │   ├── foundit.py         # Foundit adapter
│   │   ├── indeed.py          # Indeed adapter
│   │   ├── shine.py           # Shine.com adapter
│   │   └── instahyre.py       # Instahyre adapter
│   ├── ranker.py              # Groq LLM relevance & fit scoring engine
│   ├── applier.py             # Apply flow & screening Q&A solver
│   ├── exporter.py            # Phase 3 standardized Excel export engine
│   ├── scheduler.py           # 24/7 automated continuous execution daemon
│   ├── utils.py               # Anti-detection helpers, jitter delays, URL cleaner
│   └── main.py                # CLI orchestration & subcommands
├── tests/
│   └── test_agent.py          # Complete unit test suite (10 tests)
├── login_naukri.bat           # Interactive login for Naukri
├── login_linkedin.bat         # Interactive login for LinkedIn
├── login_indeed.bat           # Interactive login for Indeed
├── login_foundit.bat          # Interactive login for Foundit
├── login_shine.bat            # Interactive login for Shine
├── login_instahyre.bat        # Interactive login for Instahyre
├── start_auto_agent.bat       # 24/7 automated scheduler daemon
├── run_agent.bat              # Run single full pipeline (Scrape -> Rank -> Apply)
├── requirements.txt
├── .env.example
└── .gitignore
```

---

## ⚡ Quick Start & Deployment

### 1. One-Time Interactive Login per Platform
Launch the corresponding `.bat` file to open a visible browser and log in manually (solving any 2FA/OTP/CAPTCHA):
- 👉 **`login_naukri.bat`**
- 👉 **`login_linkedin.bat`**
- 👉 **`login_indeed.bat`**
- 👉 **`login_foundit.bat`**
- 👉 **`login_shine.bat`**
- 👉 **`login_instahyre.bat`**

Sessions are saved persistently in `data/sessions/`.

---

### 2. Run 24/7 Fully Automated Daemon
Double-click:
👉 **[`start_auto_agent.bat`](file:///d:/D_Drive/Job_search_apply_agent/start_auto_agent.bat)**

Or via terminal:
```powershell
.\venv\Scripts\python -m src.main schedule
```

---

### 3. Step-by-Step CLI Commands

```powershell
# Scrape jobs across all enabled platforms (or specify --sites)
.\venv\Scripts\python -m src.main scrape
.\venv\Scripts\python -m src.main scrape --sites "linkedin,naukri"

# Score fit with Groq LLM against resume.txt
.\venv\Scripts\python -m src.main rank

# Apply to top qualified jobs (with optional --dry-run)
.\venv\Scripts\python -m src.main apply
.\venv\Scripts\python -m src.main apply --sites linkedin --dry-run

# Run full end-to-end pipeline (Scrape -> Rank -> Apply)
.\venv\Scripts\python -m src.main run

# Export Excel report
.\venv\Scripts\python -m src.main export

# View summary & applied history in terminal
.\venv\Scripts\python -m src.main summary
.\venv\Scripts\python -m src.main applied
```

---

## 🧪 Testing & Health Check

- **Run unit tests**:
  ```powershell
  .\venv\Scripts\python -m unittest tests/test_agent.py
  ```
- **Run selector health check**:
  ```powershell
  .\venv\Scripts\python -m src.main health
  ```

