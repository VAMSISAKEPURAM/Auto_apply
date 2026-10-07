import re
from typing import List, Dict, Any, Optional
from playwright.sync_api import Page

from .base import JobPlatform
from ..utils import setup_logger, random_delay, normalize_job_url
from ..db import upsert_job, is_job_already_applied, update_job_apply_status
from ..filters import build_indeed_search_url, filter_job_card

logger = setup_logger("platform.indeed")


class IndeedPlatform(JobPlatform):
    """
    Indeed India platform adapter with experience level, location, and freshness filtering.
    """
    name: str = "indeed"
    display_name: str = "Indeed"

    def search_jobs(self, page: Page, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Scrape jobs matching search criteria from Indeed with experience and location filters."""
        search_cfg = settings.get("search", {})
        filters_cfg = settings.get("filters", {})
        keywords = search_cfg.get("keywords", ["Python Developer"])
        locations = search_cfg.get("locations", ["Bengaluru", "Remote"])
        exp_years = search_cfg.get("experience_years", 1)
        job_age_days = filters_cfg.get("max_job_age_days", 30)
        max_pages = filters_cfg.get("max_pages_per_run", 2)

        stats = {"found": 0, "new": 0, "skipped": 0, "filtered": 0}

        for keyword in keywords:
            for location in locations:
                search_url = build_indeed_search_url(
                    keyword=keyword, 
                    location=location, 
                    experience_years=exp_years, 
                    job_age_days=job_age_days
                )
                logger.info(f"[Indeed] Searching: '{keyword}' in '{location}' (Exp: {exp_years} Yrs) -> {search_url}")

                try:
                    page.goto(search_url, wait_until="domcontentloaded", timeout=35000)
                    random_delay(3.0, 5.0)
                except Exception as e:
                    logger.error(f"[Indeed] Search navigation failed: {e}")
                    continue

                for current_page in range(1, max_pages + 1):
                    # Smooth scroll
                    for _ in range(2):
                        try:
                            page.evaluate("window.scrollBy({ top: 700, behavior: 'smooth' });")
                            random_delay(1.0, 2.0)
                        except Exception:
                            pass

                    # Job card selectors on Indeed
                    cards = page.locator("div.job_seen_beacon, div[class*='jobsearch-ResultsList'] > li, div.cardOutline").all()
                    if not cards:
                        logger.warning(f"[Indeed] No job cards found on page {current_page}.")
                        break

                    logger.info(f"[Indeed] Found {len(cards)} job cards on page {current_page}.")
                    stats["found"] += len(cards)

                    for card in cards:
                        try:
                            title_el = card.locator("h2.jobTitle a, a[data-jk], a[id*='job_']").first
                            if title_el.count() == 0:
                                continue

                            title = title_el.inner_text().strip()
                            raw_href = title_el.get_attribute("href") or ""
                            jk_match = re.search(r"jk=([a-zA-Z0-9]+)", raw_href)
                            if jk_match:
                                clean_url = f"https://in.indeed.com/viewjob?jk={jk_match.group(1)}"
                            elif raw_href.startswith("http"):
                                clean_url = normalize_job_url(raw_href)
                            elif raw_href.startswith("/"):
                                clean_url = f"https://in.indeed.com{raw_href.split('?')[0]}"
                            else:
                                clean_url = ""

                            if not clean_url:
                                continue

                            company_el = card.locator("span[data-testid='company-name'], span.companyName, .company_location [class*='company']").first
                            company = company_el.inner_text().strip() if company_el.count() > 0 else ""

                            loc_el = card.locator("div[data-testid='text-location'], div.companyLocation, [class*='companyLocation']").first
                            loc_text = loc_el.inner_text().strip() if loc_el.count() > 0 else location

                            # Extract snippet / metadata
                            snippet_el = card.locator("div.job-snippet, table.jobCardShelfContainer, ul[class*='metadata']").first
                            snippet_text = snippet_el.inner_text().strip() if snippet_el.count() > 0 else ""

                            from ..filters import extract_experience_from_text
                            inferred_exp = extract_experience_from_text(f"{title} {snippet_text}")
                            exp_text = inferred_exp or f"{exp_years} Yrs"

                            job_data = {
                                "url": clean_url,
                                "title": title,
                                "company": company,
                                "location": loc_text,
                                "experience": exp_text,
                                "skills": keyword,
                                "posted_date": "Recently",
                                "apply_type": "indeed_apply",
                                "description": f"Indeed listing: {snippet_text}",
                                "platform": "indeed"
                            }

                            # Apply Filter
                            passed, reason = filter_job_card(job_data, settings)
                            if not passed:
                                stats["filtered"] += 1
                                logger.info(f"[Indeed Filter] ✗ Discarded: '{title}' at '{company}' (Reason: {reason})")
                                continue

                            inserted = upsert_job(job_data)
                            if inserted:
                                stats["new"] += 1
                                logger.info(f"[Indeed Filter] ✓ Saved: '{title}' | {company} | {loc_text} ({clean_url})")
                            else:
                                stats["skipped"] += 1

                        except Exception as e:
                            logger.debug(f"[Indeed] Error parsing card: {e}")

                    # Next page check
                    if current_page < max_pages:
                        next_btn = page.locator("a[data-testid='pagination-page-next'], a[aria-label='Next Page']").first
                        if next_btn.is_visible(timeout=2500):
                            next_btn.click()
                            random_delay(3.0, 5.0)
                        else:
                            break

        return stats

    def apply(self, page: Page, job: Dict[str, Any], settings: Dict[str, Any], resume_text: str) -> str:
        """Execute single job application on Indeed."""
        url = job.get("url", "")
        job_id = job.get("id")
        dry_run = settings.get("execution", {}).get("dry_run", True)

        logger.info(f"[Indeed] Opening Job #{job_id}: {job.get('title')} at {job.get('company')}")
        
        if is_job_already_applied("indeed", url):
            return "already applied"

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            random_delay(2.5, 4.0)
        except Exception as e:
            update_job_apply_status(job_id, "failed", error_message=f"Navigation failed: {e}")
            return "failed"

        apply_btn = page.locator("button#indeedApplyButton, button:has-text('Apply now'), a:has-text('Apply on company site')").first
        if not apply_btn.is_visible(timeout=3000):
            update_job_apply_status(job_id, "failed", error_message="Apply button not located")
            return "failed"

        btn_text = apply_btn.inner_text().strip().lower()
        if "company site" in btn_text:
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

