import json
import shutil
import time
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List
from playwright.sync_api import Playwright, Browser, BrowserContext, Page

from .utils import DATA_DIR, PROFILES_DIR, SESSIONS_DIR, setup_logger, get_browser_context_args, random_delay

logger = setup_logger("auth")

# Site-specific auth configurations
PLATFORM_AUTH_CONFIG: Dict[str, Dict[str, Any]] = {
    "naukri": {
        "display_name": "Naukri.com",
        "login_url": "https://www.naukri.com/nlogin/login",
        "profile_url": "https://www.naukri.com/mnjuser/profile",
        "logged_in_selectors": [
            ".user-name",
            ".user-profile",
            ".nI-gNb-drawer__icon",
            "a[href*='/profile']",
            ".profile-name",
            ".complete-profile",
            ".quick-links"
        ],
        "login_redirect_patterns": ["nlogin/login", "login"]
    },
    "linkedin": {
        "display_name": "LinkedIn",
        "login_url": "https://www.linkedin.com/login",
        "profile_url": "https://www.linkedin.com/feed/",
        "logged_in_selectors": [
            "a[href*='/in/']",
            "a[href*='/feed']",
            "nav.global-nav",
            "img.global-nav__me-photo",
            "div[data-identity-member-id]",
            ".feed-identity-module",
            ".global-nav__primary-link",
            "button[aria-label*='Profile']",
            "button[aria-label*='Me']"
        ],
        "login_redirect_patterns": ["linkedin.com/login", "uas/login", "checkpoint/challenge"]
    },
    "foundit": {
        "display_name": "Foundit (Monster)",
        "login_url": "https://www.foundit.in/seeker/login",
        "profile_url": "https://www.foundit.in/seeker/profile",
        "logged_in_selectors": [
            ".user-profile-summary",
            "a[href*='/profile']",
            ".user-avatar",
            "div[class*='userName']",
            ".userProfileSec"
        ],
        "login_redirect_patterns": ["seeker/login", "login"]
    },
    "indeed": {
        "display_name": "Indeed",
        "login_url": "https://secure.indeed.com/auth",
        "profile_url": "https://myjobs.indeed.com/",
        "logged_in_selectors": [
            "div[data-gnav-element='profile']",
            "a[href*='/account']",
            "button[id*='AccountMenu']",
            ".gnav-AccountMenu",
            "button[data-testid='header-user-menu']",
            "a[data-gnav-element='user-avatar']"
        ],
        "login_redirect_patterns": ["secure.indeed.com/auth", "account/login"]
    },
    "shine": {
        "display_name": "Shine.com",
        "login_url": "https://www.shine.com/myshine/login/",
        "profile_url": "https://www.shine.com/myshine/myprofile/",
        "logged_in_selectors": [
            "a[href*='/myshine/home']",
            "a[href*='/myshine/job-alerts']",
            "a[href*='/myshine/myprofile']",
            "a[href*='/myshine/']",
            ".profile_name",
            ".user_details",
            ".nav_user_name",
            "text='My Jobs'",
            "text='Job Alerts'"
        ],
        "login_redirect_patterns": ["myshine/login", "login/"]
    },
    "instahyre": {
        "display_name": "Instahyre",
        "login_url": "https://www.instahyre.com/login/",
        "profile_url": "https://www.instahyre.com/candidate/opportunities/",
        "logged_in_selectors": [
            "a[href*='/candidate/profile']",
            ".candidate-header",
            ".profile-dropdown",
            "span:has-text('Opportunities')",
            "div.candidate-nav"
        ],
        "login_redirect_patterns": ["instahyre.com/login", "candidate/login"]
    }
}


def get_platform_session_file(platform: str = "naukri") -> Path:
    """Get the storage state session JSON file path for a specific platform."""
    p_name = platform.lower()
    platform_file = SESSIONS_DIR / f"{p_name}.json"
    
    # Backward compatibility for existing Naukri session at data/session.json
    if p_name == "naukri" and not platform_file.exists():
        legacy_file = DATA_DIR / "session.json"
        if legacy_file.exists() and legacy_file.stat().st_size > 10:
            shutil.copy(legacy_file, platform_file)
            logger.info("Migrated existing Naukri session to data/sessions/naukri.json")
            
    return platform_file


def get_platform_profile_dir(platform: str = "naukri") -> Path:
    """Get persistent browser profile folder path: profiles/<platform>/."""
    profile_dir = PROFILES_DIR / platform.lower()
    profile_dir.mkdir(parents=True, exist_ok=True)
    return profile_dir


def has_platform_session(platform: str = "naukri") -> bool:
    """Check if session file exists with content."""
    session_file = get_platform_session_file(platform)
    return session_file.exists() and session_file.stat().st_size > 10


def create_platform_context(
    playwright: Playwright, 
    platform: str = "naukri", 
    headless: bool = False, 
    use_session: bool = True
) -> Tuple[Browser, BrowserContext]:
    """Launch stealth browser instance with platform session persistence."""
    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--start-maximized",
        "--new-window",
        "--window-position=100,100",
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-infobars"
    ]
    
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
    session_file = get_platform_session_file(platform)
    
    if use_session and has_platform_session(platform):
        logger.info(f"[{platform}] Loading existing session from {session_file}")
        context_options["storage_state"] = str(session_file)
    
    context = browser.new_context(**context_options)
    
    # Anti-bot stealth init script
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });
    """)
    
    return browser, context


def is_platform_session_valid(page: Page, platform: str = "naukri") -> bool:
    """
    Check if the current browser session is logged in for a platform.
    Navigates to the platform's profile/dashboard URL and inspects indicators.
    """
    config = PLATFORM_AUTH_CONFIG.get(platform.lower(), {})
    profile_url = config.get("profile_url")
    if not profile_url:
        return True

    try:
        logger.info(f"[{platform}] Validating session on {profile_url}...")
        page.goto(profile_url, wait_until="domcontentloaded", timeout=25000)
        random_delay(2.0, 3.5)
        
        current_url = page.url.lower()
        redirect_patterns = config.get("login_redirect_patterns", ["login"])
        for pattern in redirect_patterns:
            if pattern in current_url:
                logger.warning(f"[{platform}] Redirected to login page ({page.url}). Session is invalid/expired.")
                return False

        # First check logged in selectors (any visible element, not just first)
        selectors = config.get("logged_in_selectors", [])
        for selector in selectors:
            locs = page.locator(selector).all()
            for loc in locs[:6]:
                try:
                    if loc.is_visible(timeout=1000):
                        logger.info(f"[{platform}] Session valid! Detected indicator: {selector}")
                        return True
                except Exception:
                    pass

        # URL based validation fallbacks if no redirect to login occurred
        if platform.lower() == "shine" and "/myshine/" in current_url and "login" not in current_url:
            logger.info("[shine] Session valid! Current URL is in user myshine dashboard.")
            return True

        if platform.lower() == "linkedin" and ("linkedin.com/feed" in current_url or "linkedin.com/in" in current_url) and "login" not in current_url:
            logger.info("[linkedin] Session valid! Current URL is in LinkedIn feed/profile.")
            return True

        return False
    except Exception as e:
        logger.warning(f"[{platform}] Session validation check encountered notice: {e}")
        # If navigation was still on profile/feed and not login page, don't immediately fail
        try:
            cur = page.url.lower()
            if platform.lower() == "shine" and "/myshine/" in cur and "login" not in cur:
                return True
            if platform.lower() == "linkedin" and "linkedin.com/feed" in cur and "login" not in cur:
                return True
        except Exception:
            pass
        return False


def login_platform_interactive(playwright: Playwright, platform: str = "naukri") -> bool:
    """
    Open platform login page in a visible browser for human login (OTP, CAPTCHA).
    Saves session storage state and persistent profile upon completion.
    NEVER asks for, stores, or hard-codes credentials.
    """
    config = PLATFORM_AUTH_CONFIG.get(platform.lower(), {
        "display_name": platform.capitalize(),
        "login_url": f"https://www.{platform}.com/login"
    })
    
    display_name = config.get("display_name", platform.capitalize())
    login_url = config.get("login_url")
    session_file = get_platform_session_file(platform)

    logger.info(f"[{platform}] Starting interactive login flow...")
    browser, context = create_platform_context(playwright, platform=platform, headless=False, use_session=False)
    page = context.new_page()

    try:
        page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
        
        print("\n" + "=" * 65)
        print(f"  {display_name.upper()} MANUAL LOGIN REQUIRED")
        print("=" * 65)
        print(f" 1. A visible browser has opened with the {display_name} login page.")
        print(" 2. Please log in manually (enter credentials, complete OTP/CAPTCHA).")
        print(" 3. Once you reach your account dashboard/profile, return here.")
        print(" 4. Press [ENTER] to save your session.")
        print("=" * 65 + "\n")

        input(f"Press [ENTER] after logging in successfully on {display_name}...")
        
        # Save session
        logger.info(f"Saving storage state to {session_file}...")
        context.storage_state(path=str(session_file))
        print(f"\nSession saved for {platform}")

        # Verify saved session
        if is_platform_session_valid(page, platform=platform):
            print(f"[SUCCESS] Session verified and ready for {display_name}!\n")
            logger.info(f"[{platform}] Session verified and saved successfully.")
            return True
        else:
            print(f"[NOTE] Session state saved to {session_file}. Verify when running automations.\n")
            return True

    except Exception as e:
        logger.error(f"Error during interactive login on {platform}: {e}")
        return False
    finally:
        browser.close()


def ensure_authenticated_context(
    playwright: Playwright, 
    platform: str = "naukri", 
    headless: bool = False
) -> Tuple[Optional[Browser], Optional[BrowserContext]]:
    """
    Ensure a valid session exists for the platform.
    If session is missing or expired, logs warning to run login_<site>.bat and returns (None, None).
    """
    if not has_platform_session(platform):
        logger.warning(f"Session expired or not found for {platform}. Run login_{platform}.bat to authenticate.")
        print(f"\n[WARNING] Session expired for {platform}. Run login_{platform}.bat to login.\n")
        return None, None

    browser, context = create_platform_context(playwright, platform=platform, headless=headless, use_session=True)
    page = context.new_page()
    
    if not is_platform_session_valid(page, platform=platform):
        logger.warning(f"Session expired, run login_{platform}.bat")
        print(f"\n[WARNING] Session expired, run login_{platform}.bat\n")
        page.close()
        browser.close()
        return None, None

    page.close()
    return browser, context


# Aliases for backward compatibility
SESSION_FILE = get_platform_session_file("naukri")
get_session_path = lambda: get_platform_session_file("naukri")
has_saved_session = lambda: has_platform_session("naukri")
create_browser_context = lambda p, headless=False, use_session=True: create_platform_context(p, "naukri", headless, use_session)
is_session_valid = lambda page, timeout=10000: is_platform_session_valid(page, "naukri")
login_interactive = lambda p, headless=False: login_platform_interactive(p, "naukri")
