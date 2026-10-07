from typing import List, Dict, Any, Tuple
from playwright.sync_api import Playwright, Browser, BrowserContext, Page

from .base import JobPlatform
from ..auth import (
    is_session_valid as naukri_is_session_valid,
    login_interactive as naukri_login_interactive,
    ensure_authenticated_context as naukri_ensure_context,
    create_browser_context as naukri_create_context,
    has_saved_session as naukri_has_session,
    get_session_path as naukri_session_path,
)
from ..scraper import run_scraper as naukri_run_scraper
from ..applier import (
    apply_to_single_job as naukri_apply_job,
    check_and_fill_screening_questions as naukri_handle_questions,
)
from ..utils import setup_logger

logger = setup_logger("platform.naukri")


class NaukriPlatform(JobPlatform):
    """
    Naukri.com platform adapter.
    Implements search, stealth scraping, login verification, Groq-assisted chatbot handling, and apply workflow.
    """
    name: str = "naukri"
    display_name: str = "Naukri.com"

    def is_logged_in(self, page: Page) -> bool:
        """Verify if current page session is logged in to Naukri."""
        return naukri_is_session_valid(page)

    def search_jobs(self, page: Page, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Scrape jobs matching search criteria from Naukri."""
        logger.info("[Naukri] Starting job search & scraping...")
        return naukri_run_scraper(page, settings)

    def apply(self, page: Page, job: Dict[str, Any], settings: Dict[str, Any], resume_text: str) -> str:
        """Execute single job application on Naukri."""
        return naukri_apply_job(page, job, settings, resume_text)

    def handle_screening_questions(self, page: Page, job: Dict[str, Any], resume_text: str) -> List[Dict[str, str]]:
        """Handle Naukri recruiter screening chatbots and modal dialogs."""
        return naukri_handle_questions(page, job, resume_text)

    def get_authenticated_context(self, playwright: Playwright, headless: bool = False) -> Tuple[Any, Any]:
        """Create authenticated Playwright browser context for Naukri."""
        return naukri_ensure_context(playwright, platform="naukri", headless=headless)

    def login_interactive(self, playwright: Playwright, headless: bool = False) -> bool:
        """Run interactive login flow for Naukri."""
        return naukri_login_interactive(playwright, platform="naukri")

