import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from contextlib import contextmanager

from .utils import DATA_DIR, setup_logger

logger = setup_logger("db")
DB_PATH = DATA_DIR / "agent.db"


@contextmanager
def get_db_connection():
    """Get SQLite database connection with row factory enabled and auto-closing context."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    """Initialize database tables, columns, indexes, and migrate legacy rows."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE NOT NULL,
                title TEXT,
                company TEXT,
                location TEXT,
                experience TEXT,
                skills TEXT,
                posted_date TEXT,
                apply_type TEXT DEFAULT 'unknown',
                description TEXT,
                platform TEXT DEFAULT 'naukri',
                relevance_score INTEGER,
                justification TEXT,
                status TEXT DEFAULT 'scraped',
                screening_qa TEXT,
                screenshot_path TEXT,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                applied_at TIMESTAMP
            )
        """)
        
        # Check and apply auto-migration if platform column is missing in older DBs
        cursor.execute("PRAGMA table_info(jobs)")
        columns = [row["name"] if isinstance(row, sqlite3.Row) else row[1] for row in cursor.fetchall()]
        if "platform" not in columns:
            cursor.execute("ALTER TABLE jobs ADD COLUMN platform TEXT DEFAULT 'naukri'")
            logger.info("Migrated database: added 'platform' column.")

        # Migrate legacy rows: ensure Site = 'naukri' for any rows missing platform
        cursor.execute("UPDATE jobs SET platform = 'naukri' WHERE platform IS NULL OR platform = ''")

        # Indexes for fast lookup
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_url ON jobs (url)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs (relevance_score)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_platform ON jobs (platform)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_site_url ON jobs (platform, url)")
        conn.commit()

    # Automatically purge/transition active jobs that violate strict 1-2 years experience rule
    try:
        cleanup_ineligible_experience_jobs()
    except Exception as e:
        logger.debug(f"Experience cleanup notice: {e}")

    logger.info(f"Database initialized at {DB_PATH}")


def upsert_job(job_data: Dict[str, Any]) -> bool:
    """
    Insert a newly scraped job or ignore if URL already exists.
    Returns True if a new row was inserted, False if skipped.
    """
    url = job_data.get("url", "").strip()
    if not url:
        return False

    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO jobs (
                    url, title, company, location, experience, skills,
                    posted_date, apply_type, description, platform, status, created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, 'scraped', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
            """, (
                url,
                job_data.get("title", ""),
                job_data.get("company", ""),
                job_data.get("location", ""),
                job_data.get("experience", ""),
                job_data.get("skills", ""),
                job_data.get("posted_date", ""),
                job_data.get("apply_type", "unknown"),
                job_data.get("description", ""),
                job_data.get("platform", "naukri").lower()
            ))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            # Already exists in DB
            return False


def get_job_by_id(job_id: int) -> Optional[Dict[str, Any]]:
    """Retrieve single job dictionary by its primary key ID."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def is_job_already_applied(platform: str, url: str) -> bool:
    """Check if a job has already been applied to on the given platform/URL."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id FROM jobs 
            WHERE LOWER(platform) = ? AND url = ? 
              AND status IN ('applied', 'already applied', 'already_applied')
        """, (platform.lower(), url.strip()))
        return cursor.fetchone() is not None


def get_unscored_jobs(limit: int = 50, platform: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Fetch jobs that have been scraped but not yet scored by the LLM.
    If platform is specified, fetches unscored jobs for that specific platform.
    If platform is None, retrieves unscored jobs evenly/balanced across all platforms so no platform is starved.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if platform:
            cursor.execute("""
                SELECT * FROM jobs 
                WHERE status = 'scraped' AND LOWER(platform) = ? 
                ORDER BY id DESC 
                LIMIT ?
            """, (platform.lower(), limit))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        else:
            # Multi-platform fair retrieval: get unscored jobs for each distinct platform
            cursor.execute("SELECT DISTINCT LOWER(platform) as p FROM jobs WHERE status = 'scraped'")
            active_platforms = [r["p"] for r in cursor.fetchall() if r["p"]]
            if not active_platforms:
                return []

            per_platform_limit = max(5, limit // len(active_platforms))
            collected: List[Dict[str, Any]] = []
            for p_name in active_platforms:
                cursor.execute("""
                    SELECT * FROM jobs 
                    WHERE status = 'scraped' AND LOWER(platform) = ? 
                    ORDER BY id DESC 
                    LIMIT ?
                """, (p_name, per_platform_limit))
                collected.extend([dict(row) for row in cursor.fetchall()])

            # If still below total limit, backfill with remaining unscored jobs
            if len(collected) < limit:
                existing_ids = {j["id"] for j in collected}
                placeholders = ",".join("?" for _ in existing_ids) if existing_ids else "-1"
                cursor.execute(f"""
                    SELECT * FROM jobs 
                    WHERE status = 'scraped' AND id NOT IN ({placeholders})
                    ORDER BY id DESC 
                    LIMIT ?
                """, (*existing_ids, limit - len(collected)))
                collected.extend([dict(row) for row in cursor.fetchall()])

            return collected[:limit]



def update_job_score(job_id: int, score: int, justification: str, status: str):
    """Save LLM relevance score and update status."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE jobs 
            SET relevance_score = ?, justification = ?, status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (score, justification, status, job_id))
        conn.commit()


def get_jobs_for_application(
    min_score: int = 75, 
    limit: int = 10, 
    platform: Optional[str] = None,
    settings: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """Retrieve jobs ready for application stage, strictly filtered by experience requirements."""
    if settings is None:
        from .utils import load_settings
        settings = load_settings()

    target_exp = float(settings.get("search", {}).get("experience_years", 1))
    min_exp = float(settings.get("filters", {}).get("experience_min", 1))
    max_exp = float(settings.get("filters", {}).get("experience_max", 2))
    strict_exp = settings.get("filters", {}).get("strict_experience_match", True)
    inc_0_2 = settings.get("filters", {}).get("include_entry_level_0_to_2", True)

    from .filters import is_experience_matching, extract_experience_from_text

    with get_db_connection() as conn:
        cursor = conn.cursor()
        fetch_limit = max(limit * 3, 50)
        if platform:
            cursor.execute("""
                SELECT * FROM jobs 
                WHERE status = 'scored' 
                  AND relevance_score >= ?
                  AND LOWER(platform) = ?
                ORDER BY relevance_score DESC, id ASC 
                LIMIT ?
            """, (min_score, platform.lower(), fetch_limit))
        else:
            cursor.execute("""
                SELECT * FROM jobs 
                WHERE status = 'scored' 
                  AND relevance_score >= ?
                ORDER BY relevance_score DESC, id ASC 
                LIMIT ?
            """, (min_score, fetch_limit))
        rows = cursor.fetchall()
        
        qualified_jobs: List[Dict[str, Any]] = []
        for row in rows:
            job = dict(row)
            exp_str = job.get("experience", "")
            if not exp_str or not exp_str.strip():
                exp_str = extract_experience_from_text(f"{job.get('title', '')} {job.get('description', '')}") or ""

            if strict_exp and not is_experience_matching(
                exp_str, 
                target_exp_years=target_exp, 
                min_tolerance_years=min_exp, 
                max_tolerance_years=max_exp, 
                strict_match=True, 
                include_0_to_2=inc_0_2
            ):
                cursor.execute("""
                    UPDATE jobs 
                    SET status = 'skipped', 
                        error_message = ?, 
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (f"Skipped: Experience '{exp_str or 'None'}' outside strict 1-2 Yrs rule", job["id"]))
                continue

            qualified_jobs.append(job)
            if len(qualified_jobs) >= limit:
                break
        conn.commit()
        return qualified_jobs


def cleanup_ineligible_experience_jobs(settings: Optional[Dict[str, Any]] = None) -> int:
    """
    Transition any queued/scored/staged jobs whose experience violates the strict 1-2 years rule to 'skipped'.
    Returns count of jobs transitioned.
    """
    if settings is None:
        try:
            from .utils import load_settings
            settings = load_settings()
        except Exception:
            return 0

    target_exp = float(settings.get("search", {}).get("experience_years", 1))
    min_exp = float(settings.get("filters", {}).get("experience_min", 1))
    max_exp = float(settings.get("filters", {}).get("experience_max", 2))
    strict_exp = settings.get("filters", {}).get("strict_experience_match", True)
    inc_0_2 = settings.get("filters", {}).get("include_entry_level_0_to_2", True)

    if not strict_exp:
        return 0

    from .filters import is_experience_matching, extract_experience_from_text

    skipped_count = 0
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, title, description, experience FROM jobs WHERE status IN ('scored', 'staged', 'scraped')")
        rows = cursor.fetchall()
        for row in rows:
            job_id = row["id"]
            exp_str = row["experience"] or ""
            if not exp_str or not exp_str.strip():
                exp_str = extract_experience_from_text(f"{row['title'] or ''} {row['description'] or ''}") or ""

            if not is_experience_matching(
                exp_str, 
                target_exp_years=target_exp, 
                min_tolerance_years=min_exp, 
                max_tolerance_years=max_exp, 
                strict_match=True, 
                include_0_to_2=inc_0_2
            ):
                cursor.execute("""
                    UPDATE jobs 
                    SET status = 'skipped', 
                        error_message = ?, 
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (f"Skipped by 1-2 Yrs rule: Experience '{exp_str or 'Unspecified'}' outside 1-2 Yrs", job_id))
                skipped_count += 1
        conn.commit()

    if skipped_count > 0:
        logger.info(f"Cleaned up {skipped_count} jobs from queue whose experience does not match strict 1-2 Yrs requirement.")
    return skipped_count


def update_job_apply_status(
    job_id: int, 
    status: str, 
    screening_qa: Optional[str] = None, 
    screenshot_path: Optional[str] = None, 
    error_message: Optional[str] = None
):
    """Update application progression status and record to Excel atomically."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        applied_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S") if status == "applied" else None
        cursor.execute("""
            UPDATE jobs 
            SET status = ?, 
                screening_qa = COALESCE(?, screening_qa),
                screenshot_path = COALESCE(?, screenshot_path),
                error_message = COALESCE(?, error_message),
                applied_at = COALESCE(?, applied_at),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (status, screening_qa, screenshot_path, error_message, applied_at, job_id))
        conn.commit()

    # Atomic write to Excel so crash loses nothing
    try:
        from .exporter import record_application_in_excel
        job = get_job_by_id(job_id)
        if job:
            record_application_in_excel(job, status=status, reason=error_message or job.get("justification", ""))
    except Exception as e:
        logger.warning(f"Notice while recording application to Excel: {e}")


def get_summary_stats() -> Dict[str, Any]:
    """Get count of jobs across each status lifecycle."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status, COUNT(*) as count FROM jobs GROUP BY status")
        rows = cursor.fetchall()
        stats = {row["status"]: row["count"] for row in rows}
        
        cursor.execute("SELECT COUNT(*) as total FROM jobs")
        total = cursor.fetchone()["total"]
        stats["total"] = total
        return stats
