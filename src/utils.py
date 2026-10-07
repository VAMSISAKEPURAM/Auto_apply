import os
import random
import time
import logging
from logging.handlers import RotatingFileHandler
from urllib.parse import urlparse, urlunparse
from pathlib import Path
import yaml
from dotenv import load_dotenv

# Base paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"
SCREENSHOTS_DIR = PROJECT_ROOT / "screenshots"
PROFILES_DIR = PROJECT_ROOT / "profiles"
SESSIONS_DIR = DATA_DIR / "sessions"

# Ensure runtime directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
PROFILES_DIR.mkdir(parents=True, exist_ok=True)
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


# Load environment variables
load_dotenv(PROJECT_ROOT / ".env")


def load_settings():
    """Load settings from config/settings.yaml with safe defaults."""
    settings_path = CONFIG_DIR / "settings.yaml"
    if not settings_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {settings_path}")
    
    with open(settings_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    
    return config


def load_resume():
    """Load plain-text resume content."""
    resume_path = CONFIG_DIR / "resume.txt"
    if not resume_path.exists():
        raise FileNotFoundError(f"Resume file not found: {resume_path}")
    
    with open(resume_path, "r", encoding="utf-8") as f:
        return f.read().strip()


def normalize_job_url(raw_url: str) -> str:
    """
    Normalize Naukri job URLs by stripping tracking and query params.
    Example:
    'https://www.naukri.com/job-listings-python-dev-12345?src=search&sid=abc'
    -> 'https://www.naukri.com/job-listings-python-dev-12345'
    """
    if not raw_url:
        return ""
    parsed = urlparse(raw_url)
    # Reconstruct without query parameters or fragment
    clean_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
    return clean_url.rstrip("/")


def random_delay(min_sec: float = 3.0, max_sec: float = 7.0):
    """Introduce human-like jitter delay."""
    delay = random.uniform(min_sec, max_sec)
    time.sleep(delay)


def setup_logger(name: str = "naukri_agent") -> logging.Logger:
    """Setup multi-output logger with rotating file and console handlers."""
    logger = logging.getLogger(name)
    if logger.hasHandlers():
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Date-based rotating log file handler
    log_file = LOGS_DIR / "agent.log"
    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def get_browser_context_args():
    """Returns realistic browser context arguments to avoid bot detection."""
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ]
    return {
        "user_agent": random.choice(user_agents),
        "viewport": {"width": 1366, "height": 768},
        "locale": "en-US",
        "timezone_id": "Asia/Kolkata",
        "permissions": ["geolocation"],
        "geolocation": {"latitude": 12.9716, "longitude": 77.5946}, # Bengaluru approx
    }
