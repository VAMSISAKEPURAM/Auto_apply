import re
from typing import List, Dict, Any, Optional
from playwright.sync_api import Page

from .base import JobPlatform
from ..utils import setup_logger, random_delay, normalize_job_url
from ..db import upsert_job, is_job_already_applied, update_job_apply_status
from ..filters import build_foundit_search_url, filter_job_card

logger = setup_logger("platform.foundit")


class FounditPlatform(JobPlatform):
    """
    Foundit (Monster India) platform adapter with experience range and city filters.
    """
    name: str = "foundit"
    display_name: str = "Foundit (Monster)"

    def search_jobs(self, page: Page, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Scrape jobs matching search criteria from Foundit with experience and location filters."""
        search_cfg = settings.get("search", {})
        filters_cfg = settings.get("filters", {})
        keywords = search_cfg.get("keywords", ["Python Developer"])
        locations = search_cfg.get("locations", ["Bengaluru", "Remote"])
        exp_years = search_cfg.get("experience_years", 1)
        min_exp = filters_cfg.get("experience_min", 1)
        max_exp = filters_cfg.get("experience_max", 2)
        max_pages = filters_cfg.get("max_pages_per_run", 2)

        stats = {"found": 0, "new": 0, "skipped": 0, "filtered": 0}

        for keyword in keywords:
            for location in locations:
                search_url = build_foundit_search_url(
                    keyword=keyword, 
                    location=location, 
                    experience_years=exp_years,
                    min_exp=min_exp,
                    max_exp=max_exp
                )
                logger.info(f"[Foundit] Searching: '{keyword}' in '{location}' (Exp: {exp_years} Yrs) -> {search_url}")

                try:
                    page.goto(search_url, wait_until="domcontentloaded", timeout=35000)
                    random_delay(3.0, 5.0)
                except Exception as e:
                    logger.error(f"[Foundit] Search navigation failed: {e}")
                    continue

                for current_page in range(1, max_pages + 1):
                    for _ in range(2):
                        try:
                            page.evaluate("window.scrollBy({ top: 800, behavior: 'smooth' });")
                            random_delay(1.0, 2.0)
                        except Exception:
                            pass

                    cards = page.locator("div.cardContainer, div[class*='cardContainer'], div.srpResultCard, div.job-tuple").all()
                    if not cards:
                        logger.warning(f"[Foundit] No job cards found on page {current_page}.")
                        break

                    logger.info(f"[Foundit] Found {len(cards)} job cards on page {current_page}.")
                    stats["found"] += len(cards)

                    for card in cards:
                        try:
                            title_el = card.locator("h3.jobTitle a, a.jobTitle, a[class*='jobTitle']").first
                            if title_el.count() == 0:
                                continue

                            title = title_el.inner_text().strip()
                            raw_href = title_el.get_attribute("href") or ""
                            clean_url = normalize_job_url(raw_href) if raw_href.startswith("http") else f"https://www.foundit.in{raw_href.split('?')[0]}"

                            if not clean_url:
                                continue

                            comp_el = card.locator(".companyName, .company-name, a[class*='companyName']").first
                            company = comp_el.inner_text().strip() if comp_el.count() > 0 else ""

                            exp_el = card.locator(".experience, [class*='exp'], .expWrap").first
                            exp_text = exp_el.inner_text().strip() if exp_el.count() > 0 else f"{exp_years} Yrs"

                            loc_el = card.locator(".location, [class*='loc'], .locWrap").first
                            loc_text = loc_el.inner_text().strip() if loc_el.count() > 0 else location

                            skills_els = card.locator(".skillList li, .skills, [class*='skill']").all()
                            skills_text = ", ".join([s.inner_text().strip() for s in skills_els if s.inner_text().strip()])

                            job_data = {
                                "url": clean_url,
                                "title": title,
                                "company": company,
                                "location": loc_text,
                                "experience": exp_text,
                                "skills": skills_text or keyword,
                                "posted_date": "Recently",
                                "apply_type": "foundit_apply",
                                "description": f"Foundit listing for {title} at {company}",
                                "platform": "foundit"
                            }

                            passed, reason = filter_job_card(job_data, settings)
                            if not passed:
                                stats["filtered"] += 1
                                logger.info(f"[Foundit Filter] ✗ Discarded: '{title}' at '{company}' (Reason: {reason})")
                                continue

                            inserted = upsert_job(job_data)
                            if inserted:
                                stats["new"] += 1
                                logger.info(f"[Foundit Filter] ✓ Saved: '{title}' | {company} | {loc_text} ({clean_url})")
                            else:
                                stats["skipped"] += 1

                        except Exception as e:
                            logger.debug(f"[Foundit] Error parsing card: {e}")

                    # Next page check
                    if current_page < max_pages:
                        next_btn = page.locator("a.nextPage, button:has-text('Next'), .pagination a:has-text('Next')").first
                        if next_btn.is_visible(timeout=2500):
                            next_btn.click()
                            random_delay(3.0, 5.0)
                        else:
                            break

        return stats

    def apply(self, page: Page, job: Dict[str, Any], settings: Dict[str, Any], resume_text: str) -> str:
        """Execute single job application on Foundit."""
        url = job.get("url", "")
        job_id = job.get("id")
        dry_run = settings.get("execution", {}).get("dry_run", True)

        logger.info(f"[Foundit] Opening Job #{job_id}: {job.get('title')} at {job.get('company')}")
        
        if is_job_already_applied("foundit", url):
            return "already applied"

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            random_delay(2.5, 4.0)
        except Exception as e:
            update_job_apply_status(job_id, "failed", error_message=f"Navigation failed: {e}")
            return "failed"

        apply_btn = page.locator("button.applyBtn, button:has-text('Apply'), a:has-text('Apply')").first
        if not apply_btn.is_visible(timeout=3000):
            update_job_apply_status(job_id, "failed", error_message="Apply button not located")
            return "failed"

        btn_text = apply_btn.inner_text().strip().lower()
        if "company site" in btn_text or "external" in btn_text:
            update_job_apply_status(job_id, "external redirect", error_message="External employer website redirect")
            return "external redirect"

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

