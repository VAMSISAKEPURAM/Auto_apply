import unittest
import os
import time
import tempfile
from pathlib import Path

from src.db import init_db, upsert_job, get_unscored_jobs, update_job_score, get_jobs_for_application, get_summary_stats
from src.utils import normalize_job_url, load_settings, load_resume
from src.ranker import parse_json_from_response


class TestNaukriAgent(unittest.TestCase):
    def test_url_normalization(self):
        raw = "https://www.naukri.com/job-listings-python-dev-12345?src=search&sid=abc&xp=1"
        clean = normalize_job_url(raw)
        self.assertEqual(clean, "https://www.naukri.com/job-listings-python-dev-12345")

    def test_settings_and_resume_loading(self):
        settings = load_settings()
        self.assertIn("search", settings)
        self.assertIn("filters", settings)
        resume = load_resume()
        self.assertTrue(len(resume) > 50)

    def test_json_parsing(self):
        sample_markdown = "```json\n{\"score\": 88, \"justification\": \"Great match for Python\"}\n```"
        parsed = parse_json_from_response(sample_markdown)
        self.assertEqual(parsed["score"], 88)
        self.assertEqual(parsed["justification"], "Great match for Python")

    def test_db_lifecycle(self):
        init_db()
        test_url = f"https://www.naukri.com/job-listings-test-sample-job-{int(time.time()*1000)}"
        job_data = {
            "url": test_url,
            "title": "Senior Python Developer",
            "company": "Tech Corp",
            "location": "Bengaluru",
            "experience": "3-5 Yrs",
            "skills": "Python, FastAPI, Docker",
            "posted_date": "1 day ago",
            "description": "Looking for backend engineer"
        }
        
        # Test insert
        inserted = upsert_job(job_data)
        # Deduplication test
        duplicate = upsert_job(job_data)
        self.assertFalse(duplicate)

        # Query unscored
        unscored = get_unscored_jobs(limit=500)
        matching = [j for j in unscored if j["url"] == job_data["url"]]
        self.assertTrue(len(matching) >= 1)
        job_id = matching[0]["id"]

        # Score job
        update_job_score(job_id, 85, "Matches Python experience well", "scored")
        
        # Verify eligible for apply
        eligible = get_jobs_for_application(min_score=75)
        self.assertTrue(any(j["id"] == job_id for j in eligible))

        # Check summary stats
        stats = get_summary_stats()
        self.assertIn("total", stats)


if __name__ == "__main__":
    unittest.main()
