import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from .utils import DATA_DIR, setup_logger

logger = setup_logger("db")
DB_PATH = DATA_DIR / "agent.db"


def get_db_connection() -> sqlite3.Connection:
    """Get SQLite database connection with row factory enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize database tables and indexes."""
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
        
        # Indexes for fast lookup
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_url ON jobs (url)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs (relevance_score)")
        conn.commit()
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
                    posted_date, apply_type, description, status, created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, 'scraped', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
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
                job_data.get("description", "")
            ))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            # Already exists in DB
            return False


def get_unscored_jobs(limit: int = 50) -> List[Dict[str, Any]]:
    """Fetch jobs that have been scraped but not yet scored by the LLM."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM jobs 
            WHERE status = 'scraped' 
            ORDER BY id ASC 
            LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


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


def get_jobs_for_application(min_score: int = 75, limit: int = 10) -> List[Dict[str, Any]]:
    """Retrieve jobs ready for application stage."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM jobs 
            WHERE status = 'scored' 
              AND relevance_score >= ?
            ORDER BY relevance_score DESC, id ASC 
            LIMIT ?
        """, (min_score, limit))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def update_job_apply_status(
    job_id: int, 
    status: str, 
    screening_qa: Optional[str] = None, 
    screenshot_path: Optional[str] = None, 
    error_message: Optional[str] = None
):
    """Update application progression status (staged, applied, manual_needed, failed, skipped)."""
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
