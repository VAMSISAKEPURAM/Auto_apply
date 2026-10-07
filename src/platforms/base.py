from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple
from playwright.sync_api import Playwright, Browser, BrowserContext, Page


class JobPlatform(ABC):
    """
    Abstract Base Class for job platform adapters.
    Each hiring platform (Naukri, LinkedIn, Indeed, etc.) implements this interface.
    """
    name: str = "base"
    display_name: str = "Base Platform"

    def is_logged_in(self, page: Page) -> bool:
        """
        Check if the current browser page/session is authenticated on the platform.
        """
        from ..auth import is_platform_session_valid
        return is_platform_session_valid(page, platform=self.name)

    def get_authenticated_context(
        self, 
        playwright: Playwright, 
        headless: bool = False
    ) -> Tuple[Optional[Browser], Optional[BrowserContext]]:
        """
        Create and return an authenticated browser context for this platform.
        Returns (None, None) if session is expired or missing.
        """
        from ..auth import ensure_authenticated_context
        return ensure_authenticated_context(playwright, platform=self.name, headless=headless)

    def login_interactive(self, playwright: Playwright, headless: bool = False) -> bool:
        """
        Launch visible browser for interactive manual login and session persistence.
        """
        from ..auth import login_platform_interactive
        return login_platform_interactive(playwright, platform=self.name)

    @abstractmethod
    def search_jobs(self, page: Page, settings: Dict[str, Any]) -> Dict[str, Any]:
        """
        Search listings using configured keywords/locations and store new jobs in the DB.
        Returns dict with scrape statistics: {"found": int, "new": int, "skipped": int}
        """
        pass

    @abstractmethod
    def apply(self, page: Page, job: Dict[str, Any], settings: Dict[str, Any], resume_text: str) -> str:
        """
        Process application flow for a single job posting.
        Returns status string: 'applied', 'staged', 'manual_needed', 'skipped', or 'failed'.
        """
        pass

    @abstractmethod
    def handle_screening_questions(self, page: Page, job: Dict[str, Any], resume_text: str) -> List[Dict[str, str]]:
        """
        Detect and fill screening questions/chatbots on the platform.
        Returns list of {"question": str, "answer": str}.
        """
        pass
