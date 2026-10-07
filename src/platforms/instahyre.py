import re
from typing import List, Dict, Any, Optional
from playwright.sync_api import Page

from .base import JobPlatform
from ..utils import setup_logger, random_delay, normalize_job_url
from ..db import upsert_job, is_job_already_applied, update_job_apply_status
from ..filters import build_instahyre_search_url, filter_job_card

logger = setup_logger("platform.instahyre")


class InstahyrePlatform(JobPlatform):
    """
    Instahyre platform adapter with experience and city filters.
    """
    name: str = "instahyre"
    display_name: str = "Instahyre"

    def search_jobs(self, page: Page, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Scrape opportunities matching search criteria from Instahyre with experience and city filters."""
        search_cfg = settings.get("search", {})
        filters_cfg = settings.get("filters", {})
        keywords = search_cfg.get("keywords", ["Python Developer"])
        locations = search_cfg.get("locations", ["Bengaluru", "Remote"])
        exp_years = search_cfg.get("experience_years", 1)
        max_pages = filters_cfg.get("max_pages_per_run", 2)

        stats = {"found": 0, "new": 0, "skipped": 0, "filtered": 0}

        for keyword in keywords:
            for location in locations:
                search_url = build_instahyre_search_url(
                    keyword=keyword, 
                    location=location, 
                    experience_years=exp_years
                )
                logger.info(f"[Instahyre] Searching: '{keyword}' in '{location}' (Exp: {exp_years} Yrs) -> {search_url}")

                try:
                    page.goto(search_url, wait_until="domcontentloaded", timeout=35000)
                    random_delay(3.0, 5.0)
                except Exception as e:
                    logger.error(f"[Instahyre] Search navigation failed: {e}")
                    continue

                for current_page in range(1, max_pages + 1):
                    for _ in range(2):
                        try:
                            page.evaluate("window.scrollBy({ top: 800, behavior: 'smooth' });")
                            random_delay(1.0, 2.0)
                        except Exception:
                            pass

                    cards = page.locator("div.opportunity-card, div[id*='employer-'], div.employer-row, .opportunity-details").all()
                    if not cards:
                        logger.warning(f"[Instahyre] No job cards found on page {current_page}.")
                        break

                    logger.info(f"[Instahyre] Found {len(cards)} job cards on page {current_page}.")
                    stats["found"] += len(cards)

                    for card in cards:
                        try:
                            title_el = card.locator("h2.opportunity-title, .job-title, a[href*='/job-']").first
                            if title_el.count() == 0:
                                continue

                            title = title_el.inner_text().strip()
                            raw_href = title_el.get_attribute("href") or ""
                            clean_url = normalize_job_url(raw_href) if raw_href.startswith("http") else f"https://www.instahyre.com{raw_href.split('?')[0]}"

                            if not clean_url:
                                continue

                            comp_el = card.locator(".company-name, [class*='company-name']").first
                            company = comp_el.inner_text().strip() if comp_el.count() > 0 else ""

                            loc_el = card.locator(".location, [class*='location']").first
                            loc_text = loc_el.inner_text().strip() if loc_el.count() > 0 else location

                            skills_el = card.locator(".skills, .skill-tag, [class*='skills']").first
                            skills_text = skills_el.inner_text().strip() if skills_el.count() > 0 else keyword

                            job_data = {
                                "url": clean_url,
                                "title": title,
                                "company": company,
                                "location": loc_text,
                                "experience": f"{exp_years} Yrs",
                                "skills": skills_text,
                                "posted_date": "Recently",
                                "apply_type": "instahyre_apply",
                                "description": f"Instahyre opportunity for {title} at {company}",
                                "platform": "instahyre"
                            }

                            passed, reason = filter_job_card(job_data, settings)
                            if not passed:
                                stats["filtered"] += 1
                                logger.info(f"[Instahyre Filter] ✗ Discarded: '{title}' at '{company}' (Reason: {reason})")
                                continue

                            inserted = upsert_job(job_data)
                            if inserted:
                                stats["new"] += 1
                                logger.info(f"[Instahyre Filter] ✓ Saved: '{title}' | {company} | {loc_text} ({clean_url})")
                            else:
                                stats["skipped"] += 1

                        except Exception as e:
                            logger.debug(f"[Instahyre] Error parsing card: {e}")

                    # Next page check
                    if current_page < max_pages:
                        next_btn = page.locator("a.next-page, button:has-text('Next'), .pagination a:has-text('Next')").first
                        if next_btn.is_visible(timeout=2500):
                            next_btn.click()
                            random_delay(3.0, 5.0)
                        else:
                            break

        return stats

    def apply(self, page: Page, job: Dict[str, Any], settings: Dict[str, Any], resume_text: str) -> str:
        """Execute single job application on Instahyre."""
        url = job.get("url", "")
        job_id = job.get("id")
        dry_run = settings.get("execution", {}).get("dry_run", True)

        logger.info(f"[Instahyre] Opening Job #{job_id}: {job.get('title')} at {job.get('company')}")
        
        if is_job_already_applied("instahyre", url):
            return "already applied"

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            random_delay(2.5, 4.0)
        except Exception as e:
            update_job_apply_status(job_id, "failed", error_message=f"Navigation failed: {e}")
            return "failed"

        apply_btn = page.locator("button:has-text('Apply'), button:has-text('Interested'), .btn-interested").first
        if not apply_btn.is_visible(timeout=3000):
            update_job_apply_status(job_id, "failed", error_message="Apply button not located")
            return "failed"

        if dry_run:
            update_job_apply_status(job_id, "staged")
            return "staged"

        try:
            apply_btn.click()
            random_delay(2.0, 3.5)
            update_job_apply_status(job_id, "applied")
            return "applied"
        except Exception as e:
            update_job_apply_status(job_id, "failed", error_message=str(e))
            return "failed"

    def handle_screening_questions(self, page: Page, job: Dict[str, Any], resume_text: str) -> List[Dict[str, str]]:
        return []

