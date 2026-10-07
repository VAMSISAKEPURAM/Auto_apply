import re
import urllib.parse
from typing import List, Dict, Any
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from .utils import load_settings, normalize_job_url, random_delay, setup_logger
from .db import upsert_job
from .filters import build_naukri_search_url, filter_job_card, is_experience_matching, is_location_matching

logger = setup_logger("scraper")


def construct_search_url(keyword: str, location: str = "", experience_years: int = 1, job_age_days: int = 30) -> str:
    """
    Construct resilient Naukri search URL with experience, city, and freshness filters.
    """
    return build_naukri_search_url(
        keyword=keyword, 
        location=location, 
        experience_years=experience_years, 
        job_age_days=job_age_days
    )


def scroll_page_smoothly(page: Page):
    """Smooth human-like scrolling to trigger lazy loaded job tuples."""
    try:
        page.evaluate("""
            window.scrollBy({
                top: window.innerHeight * 0.7,
                behavior: 'smooth'
            });
        """)
        random_delay(0.8, 1.5)
        page.evaluate("""
            window.scrollBy({
                top: window.innerHeight * 0.7,
                behavior: 'smooth'
            });
        """)
        random_delay(0.8, 1.5)
    except Exception as e:
        logger.debug(f"Scroll step notice: {e}")


def extract_job_card(card) -> Dict[str, Any]:
    """Extract structured details from a single Naukri job card element."""
    job = {
        "title": "",
        "url": "",
        "company": "",
        "location": "",
        "experience": "",
        "skills": "",
        "posted_date": "",
        "apply_type": "unknown",
        "description": ""
    }

    try:
        # Title & URL
        title_el = card.locator("a.title, .title a, a[class*='title']").first
        if title_el.count() > 0:
            job["title"] = title_el.inner_text().strip()
            raw_url = title_el.get_attribute("href") or ""
            job["url"] = normalize_job_url(raw_url)

        # Company
        comp_el = card.locator("a.comp-name, .comp-name, a[class*='comp-name'], .companyInfo a").first
        if comp_el.count() > 0:
            job["company"] = comp_el.inner_text().strip()

        # Experience
        exp_el = card.locator(".exp-wrap, .exp, .experience, [class*='exp-wrap']").first
        if exp_el.count() > 0:
            job["experience"] = exp_el.inner_text().strip()

        # Location
        loc_el = card.locator(".loc-wrap, .locWdth, .location, [class*='loc-wrap']").first
        if loc_el.count() > 0:
            job["location"] = loc_el.inner_text().strip()

        # Description / Snippet
        desc_el = card.locator(".job-desc, .job-description, .desc, [class*='job-desc']").first
        if desc_el.count() > 0:
            job["description"] = desc_el.inner_text().strip()

        # Skills Tags
        skill_els = card.locator(".tags-list li, .tag-li, .dots-wrapper li, [class*='tag-li']").all()
        skills = [el.inner_text().strip() for el in skill_els if el.inner_text().strip()]
        job["skills"] = ", ".join(skills)

        # Posted date
        date_el = card.locator(".date, .posted-by, [class*='job-post-day'], [class*='date']").first
        if date_el.count() > 0:
            job["posted_date"] = date_el.inner_text().strip()

    except Exception as e:
        logger.debug(f"Error parsing partial card info: {e}")

    return job


def scrape_search_results(
    page: Page, 
    keyword: str, 
    location: str, 
    settings: Dict[str, Any], 
    max_pages: int = 2
) -> Dict[str, int]:
    """
    Search and scrape jobs across pages for a specific keyword and location with full filtering.
    """
    search_cfg = settings.get("search", {})
    filters_cfg = settings.get("filters", {})
    exp_years = search_cfg.get("experience_years", 1)
    job_age_days = filters_cfg.get("max_job_age_days", 30)

    url = construct_search_url(
        keyword=keyword, 
        location=location, 
        experience_years=exp_years, 
        job_age_days=job_age_days
    )
    logger.info(f"[Naukri] Navigating to filtered search URL: {url}")
    
    total_found = 0
    total_new = 0
    total_filtered = 0
    
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
    except Exception as e:
        logger.error(f"[Naukri] Failed to load search page: {e}")
        return {"found": 0, "new": 0, "filtered": 0}

    for current_page in range(1, max_pages + 1):
        logger.info(f"[Naukri] Scraping page {current_page}/{max_pages} for '{keyword}' in '{location}' (Exp: {exp_years} Yrs)...")
        
        # Human-like delay after page loads
        random_delay(3.5, 6.0)
        scroll_page_smoothly(page)

        # Potential selectors for job tuple container in Naukri
        card_selectors = [
            ".srp-jobtuple-wrapper",
            ".cust-job-tuple",
            "article.jobTuple",
            "div[data-job-id]",
            ".jobTuple"
        ]
        
        cards = []
        for selector in card_selectors:
            matched = page.locator(selector).all()
            if matched:
                cards = matched
                logger.info(f"[Naukri] Found {len(cards)} job listings using selector '{selector}'")
                break

        if not cards:
            logger.warning(f"[Naukri] No job cards found on page {current_page}. Naukri layout might have changed or CAPTCHA shown.")
            break

        page_new = 0
        page_filtered = 0
        for card in cards:
            job_info = extract_job_card(card)
            if not (job_info.get("url") and job_info.get("title")):
                continue

            total_found += 1
            job_info["platform"] = "naukri"

            # Apply Experience, City & Role Filters
            passed, reason = filter_job_card(job_info, settings)
            if not passed:
                page_filtered += 1
                total_filtered += 1
                logger.info(f"[Naukri Filter] ✗ Discarded: '{job_info['title']}' at '{job_info['company']}' (Reason: {reason})")
                continue

            # If passed, store in database
            is_new = upsert_job(job_info)
            if is_new:
                page_new += 1
                total_new += 1
                logger.info(f"[Naukri Filter] ✓ Saved: '{job_info['title']}' | {job_info['company']} | {job_info['location']} | Exp: {job_info['experience']}")

        logger.info(f"[Naukri] Page {current_page} complete: {len(cards)} cards seen, {page_new} newly saved, {page_filtered} discarded by filters.")

        # Check for next page
        if current_page < max_pages:
            try:
                next_button = page.locator("a.styles_btn__f8Vaq:has-text('Next'), a:has-text('Next'), .pagination a:has-text('Next')").first
                if next_button.is_visible(timeout=3000):
                    logger.info("[Naukri] Clicking Next page button...")
                    next_button.click()
                    random_delay(3.0, 5.0)
                else:
                    logger.info("[Naukri] No next page button visible. End of search results.")
                    break
            except Exception as e:
                logger.info(f"[Naukri] Pagination completed or Next button not clickable: {e}")
                break

    return {"found": total_found, "new": total_new, "filtered": total_filtered}


def run_scraper(page: Page, settings: Dict[str, Any]) -> Dict[str, int]:
    """Execute full search across all configured keywords and locations."""
    search_cfg = settings.get("search", {})
    keywords = search_cfg.get("keywords", ["Python Developer"])
    locations = search_cfg.get("locations", [""])
    max_pages = settings.get("filters", {}).get("max_pages_per_run", 2)

    total_stats = {"found": 0, "new": 0, "filtered": 0}
    
    for kw in keywords:
        for loc in locations:
            logger.info(f"\n--- Searching: Keyword='{kw}', Location='{loc}' ---")
            stats = scrape_search_results(page, keyword=kw, location=loc, settings=settings, max_pages=max_pages)
            total_stats["found"] += stats["found"]
            total_stats["new"] += stats["new"]
            total_stats["filtered"] += stats.get("filtered", 0)
            random_delay(4.0, 7.0)

    logger.info(
        f"\n[Naukri] Scraping Run Summary: {total_stats['found']} listings evaluated, "
        f"{total_stats['new']} new qualified jobs stored, {total_stats['filtered']} filtered out."
    )
    return total_stats
