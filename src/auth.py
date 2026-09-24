import json
import time
from pathlib import Path
from playwright.sync_api import Playwright, Browser, BrowserContext, Page

from .utils import DATA_DIR, setup_logger, get_browser_context_args, random_delay

logger = setup_logger("auth")
SESSION_FILE = DATA_DIR / "session.json"
LOGIN_URL = "https://www.naukri.com/nlogin/login"
PROFILE_URL = "https://www.naukri.com/mnjuser/profile"


def get_session_path() -> Path:
    return SESSION_FILE


def has_saved_session() -> bool:
    return SESSION_FILE.exists() and SESSION_FILE.stat().st_size > 10


def create_browser_context(playwright: Playwright, headless: bool = False, use_session: bool = True) -> tuple[Browser, BrowserContext]:
    """Launch stealth browser instance with optional session persistence."""
    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--start-maximized",
        "--new-window",
        "--window-position=100,100",
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-infobars"
    ]
    
    # Try launching with local Google Chrome channel first, fallback to bundled Chromium
    try:
        browser = playwright.chromium.launch(
            headless=headless,
            channel="chrome",
            args=launch_args
        )
    except Exception:
        browser = playwright.chromium.launch(
            headless=headless,
            args=launch_args
        )
    
    context_options = get_browser_context_args()
    if use_session and has_saved_session():
        logger.info(f"Loading existing session from {SESSION_FILE}")
        context_options["storage_state"] = str(SESSION_FILE)
    
    context = browser.new_context(**context_options)
    
    # Anti-bot stealth init script
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });
    """)
    
    return browser, context


def is_session_valid(page: Page, timeout: int = 10000) -> bool:
    """
    Check if the current browser session is logged in.
    Navigates to Naukri profile page and checks for profile elements.
    """
    try:
        logger.info("Validating session on Naukri profile page...")
        page.goto(PROFILE_URL, wait_until="domcontentloaded", timeout=15000)
        random_delay(2.0, 3.5)
        
        # Selectors unique to logged-in users on Naukri
        logged_in_selectors = [
            ".user-name",
            ".user-profile",
            ".nI-gNb-drawer__icon",
            "a[href*='/profile']",
            ".profile-name",
            ".complete-profile",
            ".quick-links"
        ]
        
        for selector in logged_in_selectors:
            if page.locator(selector).first.is_visible(timeout=2000):
                logger.info(f"Session valid! Detected logged-in indicator: {selector}")
                return True
                
        # Check URL hasn't been redirected back to login page
        current_url = page.url
        if "nlogin/login" in current_url or "login" in current_url.lower():
            logger.warning(f"Redirected to login page ({current_url}). Session is invalid/expired.")
            return False

        return False
    except Exception as e:
        logger.warning(f"Session validation check failed: {e}")
        return False


def login_interactive(playwright: Playwright, headless: bool = False) -> bool:
    """
    Open Naukri login page in a visible browser for human login (OTP, CAPTCHA).
    Saves session storage state upon completion.
    """
    logger.info("Starting interactive login flow...")
    browser, context = create_browser_context(playwright, headless=False, use_session=False)
    page = context.new_page()

    try:
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
        
        print("\n" + "=" * 60)
        print(" NAUKRI MANUAL LOGIN REQUIRED")
        print("=" * 60)
        print(" 1. A browser window has opened with the Naukri login page.")
        print(" 2. Please enter your email/username, password, and any OTP/CAPTCHA.")
        print(" 3. Once you are successfully logged in to your account dashboard,")
        print("    return to this terminal and press [ENTER] to save your session.")
        print("=" * 60 + "\n")

        input("Press [ENTER] after logging in successfully in the browser...")
        
        # Validate if user is logged in
        logger.info("Saving storage state to session.json...")
        context.storage_state(path=str(SESSION_FILE))
        
        # Verify saved session
        if is_session_valid(page):
            print("\n[SUCCESS] Session successfully saved and verified!\n")
            logger.info("Session verified and saved successfully.")
            return True
        else:
            print("\n[WARNING] Logged-in profile indicators not detected yet. Saved current state anyway.\n")
            return True

    except Exception as e:
        logger.error(f"Error during interactive login: {e}")
        return False
    finally:
        browser.close()


def ensure_authenticated_context(playwright: Playwright, headless: bool = False) -> tuple[Browser, BrowserContext]:
    """
    Ensure a valid session exists before proceeding with actions.
    If session is missing or expired, prompts for interactive login.
    """
    if not has_saved_session():
        logger.info("No saved session found. Triggering login...")
        login_interactive(playwright, headless=False)

    browser, context = create_browser_context(playwright, headless=headless, use_session=True)
    page = context.new_page()
    
    if not is_session_valid(page):
        logger.warning("Existing session is expired or invalid. Re-authenticating...")
        page.close()
        browser.close()
        login_interactive(playwright, headless=False)
        browser, context = create_browser_context(playwright, headless=headless, use_session=True)

    page.close()
    return browser, context
