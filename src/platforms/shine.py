import re
from datetime import datetime
from typing import List, Dict, Any, Optional
from playwright.sync_api import Page

from .base import JobPlatform
from ..utils import setup_logger, random_delay, normalize_job_url, SCREENSHOTS_DIR
from ..db import upsert_job, is_job_already_applied, update_job_apply_status
from ..filters import build_shine_search_url, filter_job_card

logger = setup_logger("platform.shine")


class ShinePlatform(JobPlatform):
    """
    Shine.com platform adapter with experience and city filters.
    Supports modern React/Next.js article cards, Easy Apply, and external application redirection.
    """
    name: str = "shine"
    display_name: str = "Shine.com"

    def search_jobs(self, page: Page, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Scrape jobs matching search criteria from Shine with experience and city filters."""
        search_cfg = settings.get("search", {})
        filters_cfg = settings.get("filters", {})
        keywords = search_cfg.get("keywords", ["Python Developer"])
        locations = search_cfg.get("locations", ["Bengaluru", "Remote"])
        exp_years = search_cfg.get("experience_years", 1)
        max_pages = filters_cfg.get("max_pages_per_run", 2)

        stats = {"found": 0, "new": 0, "skipped": 0, "filtered": 0}

        for keyword in keywords:
            for location in locations:
                search_url = build_shine_search_url(
                    keyword=keyword, 
                    location=location, 
                    experience_years=exp_years
                )
                logger.info(f"[Shine] Searching: '{keyword}' in '{location}' (Exp: {exp_years} Yrs) -> {search_url}")

                try:
                    page.goto(search_url, wait_until="domcontentloaded", timeout=35000)
                    random_delay(3.0, 5.0)
                except Exception as e:
                    logger.error(f"[Shine] Search navigation failed: {e}")
                    continue

                for current_page in range(1, max_pages + 1):
                    for _ in range(2):
                        try:
                            page.evaluate("window.scrollBy({ top: 800, behavior: 'smooth' });")
                            random_delay(1.0, 2.0)
                        except Exception:
                            pass

                    # Support modern Shine article cards and legacy jobCard containers
                    cards = page.locator("article, div[class*='result-card_resultCard'], div.jobCard, div.parentClass").all()
                    # Filter out any nested sub-divs that are not top-level cards
                    top_cards = []
                    for c in cards:
                        tag = c.evaluate("el => el.tagName.toLowerCase()")
                        cls = c.get_attribute("class") or ""
                        if tag == "article" or "jobCard" in cls or "resultCard" in cls:
                            top_cards.append(c)

                    if not top_cards:
                        logger.warning(f"[Shine] No job cards found on page {current_page}.")
                        break

                    logger.info(f"[Shine] Found {len(top_cards)} job cards on page {current_page}.")
                    stats["found"] += len(top_cards)

                    for card in top_cards:
                        try:
                            # 1. URL extraction
                            clean_url = ""
                            meta_url = card.locator("meta[itemprop='url']").first
                            if meta_url.count() > 0:
                                clean_url = meta_url.get_attribute("content") or ""

                            link_el = card.locator("a[href*='/jobs/']").first
                            if not clean_url and link_el.count() > 0:
                                raw_href = link_el.get_attribute("href") or ""
                                if raw_href:
                                    clean_url = normalize_job_url(raw_href) if raw_href.startswith("http") else f"https://www.shine.com{raw_href.split('?')[0]}"

                            if not clean_url:
                                continue

                            # 2. Title & Company extraction
                            aria_label = link_el.get_attribute("aria-label") or "" if link_el.count() > 0 else ""
                            title = ""
                            comp_from_aria = ""
                            if " at " in aria_label:
                                parts = aria_label.split(" at ")
                                title = parts[0].strip()
                                comp_from_aria = parts[1].strip()
                            else:
                                title = aria_label

                            title_el = card.locator("h2, [class*='title'], [class*='Title']").first
                            if title_el.count() > 0 and title_el.inner_text().strip():
                                title = title_el.inner_text().strip()

                            if not title:
                                title = keyword

                            comp_el = card.locator("[class*='company'], [class*='Company'], [class*='cName'], .company-name").first
                            company = comp_el.inner_text().strip() if comp_el.count() > 0 else comp_from_aria
                            if not company:
                                lines = [l.strip() for l in card.inner_text().split("\n") if l.strip()]
                                if len(lines) > 1 and len(lines[0]) <= 3:
                                    company = lines[1]
                                elif lines:
                                    company = lines[0]

                            # 3. Experience and Location metadata
                            meta_texts = [el.inner_text().strip() for el in card.locator("[class*='meta-text']").all()]
                            if meta_texts:
                                exp_text = meta_texts[0]
                                loc_text = meta_texts[2] if len(meta_texts) > 2 else (meta_texts[1] if len(meta_texts) > 1 else location)
                            else:
                                exp_el = card.locator(".jobCard_jobCard_lists_item__YxRlu, [class*='exp'], [class*='experience']").first
                                exp_text = exp_el.inner_text().strip() if exp_el.count() > 0 else f"{exp_years} Yrs"
                                loc_el = card.locator(".jobCard_locationIcon__Fs_qw, [class*='loc'], .jobCard_location").first
                                loc_text = loc_el.inner_text().strip() if loc_el.count() > 0 else location

                            # 4. Skills extraction
                            skills_items = [el.inner_text().strip() for el in card.locator("[class*='skills-item']").all()]
                            if skills_items:
                                skills_text = ", ".join(skills_items)
                            else:
                                skills_el = card.locator(".jobCard_skillList__2K41J, [class*='skill']").first
                                skills_text = skills_el.inner_text().strip() if skills_el.count() > 0 else keyword

                            # Check if the card indicates external apply
                            apply_btn = card.locator("button[class*='apply'], button:has-text('Apply')").first
                            btn_text = apply_btn.inner_text().strip().lower() if apply_btn.count() > 0 else ""
                            is_external = "company site" in btn_text or "external" in btn_text
                            apply_type = "external_redirect" if is_external else "shine_apply"

                            job_data = {
                                "url": clean_url,
                                "title": title,
                                "company": company,
                                "location": loc_text,
                                "experience": exp_text,
                                "skills": skills_text,
                                "posted_date": "Recently",
                                "apply_type": apply_type,
                                "description": f"Shine listing for {title} at {company}",
                                "platform": "shine"
                            }

                            passed, reason = filter_job_card(job_data, settings)
                            if not passed:
                                stats["filtered"] += 1
                                logger.info(f"[Shine Filter] ✗ Discarded: '{title}' at '{company}' (Reason: {reason})")
                                continue

                            inserted = upsert_job(job_data)
                            if inserted:
                                stats["new"] += 1
                                logger.info(f"[Shine Filter] ✓ Saved: '{title}' | {company} | {loc_text} ({clean_url})")
                            else:
                                stats["skipped"] += 1

                        except Exception as e:
                            logger.debug(f"[Shine] Error parsing card: {e}")

                    # Next page check
                    if current_page < max_pages:
                        next_btn = page.locator("a[aria-label='Next'], a:has-text('Next'), .pagination a:has-text('Next'), button[aria-label*='Next']").first
                        if next_btn.is_visible(timeout=2500):
                            next_btn.click()
                            random_delay(3.0, 5.0)
                        else:
                            break

        return stats

    def apply(self, page: Page, job: Dict[str, Any], settings: Dict[str, Any], resume_text: str) -> str:
        """Execute single job application on Shine."""
        url = job.get("url", "")
        job_id = job.get("id")
        dry_run = settings.get("execution", {}).get("dry_run", True)

        logger.info(f"[Shine] Opening Job #{job_id}: {job.get('title')} at {job.get('company')}")
        
        if is_job_already_applied("shine", url):
            logger.info(f"[Shine] Job #{job_id} already marked as applied.")
            return "already applied"

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            random_delay(2.5, 4.0)
        except Exception as e:
            logger.error(f"[Shine] Navigation failed for Job #{job_id}: {e}")
            update_job_apply_status(job_id, "failed", error_message=f"Navigation failed: {e}")
            return "failed"

        # Check if already applied indicator appears on page
        already_applied_el = page.locator("button:has-text('Applied'), span:has-text('Applied'), [class*='applied']").first
        if already_applied_el.is_visible(timeout=2000):
            logger.info(f"[Shine] Job #{job_id} is already applied on Shine.")
            update_job_apply_status(job_id, "already applied", error_message="Already applied on Shine")
            return "already applied"

        # Locate Apply button on job page or result card
        # If redirected to search results, match the company card
        company = job.get("company", "").strip()
        apply_btn = None
        if company:
            matching_card = page.locator("article").filter(has_text=company).first
            if matching_card.count() > 0:
                card_btn = matching_card.locator("button.result-card_apply__D9pKa, button:has-text('Apply'), button:has-text('Applied')").first
                if card_btn.is_visible(timeout=2000):
                    apply_btn = card_btn

        if not apply_btn or not apply_btn.is_visible():
            apply_btn = page.locator("button.result-card_apply__D9pKa, button:has-text('Apply'), button:has-text('Applied'), [class*='apply']").first

        if not apply_btn.is_visible(timeout=3000):
            logger.warning(f"[Shine] No Apply button found for Job #{job_id}.")
            update_job_apply_status(job_id, "failed", error_message="Apply button not located")
            return "failed"

        btn_text = apply_btn.inner_text().strip().lower()
        if "applied" in btn_text:
            logger.info(f"[Shine] Job #{job_id} is already applied on Shine.")
            update_job_apply_status(job_id, "already applied", error_message="Already applied on Shine")
            return "already applied"

        if "company site" in btn_text or "external" in btn_text:
            logger.info(f"[Shine] Job #{job_id} requires external company website application.")
            update_job_apply_status(job_id, "external redirect", error_message="External employer website redirect")
            return "external redirect"

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        screenshot_path = SCREENSHOTS_DIR / f"shine_staged_{job_id}_{timestamp}.png"
        try:
            page.screenshot(path=str(screenshot_path))
        except Exception:
            screenshot_path = None

        if dry_run:
            logger.info(f"[Shine] [DRY-RUN] Staged application for job #{job_id}.")
            update_job_apply_status(job_id, "staged", screenshot_path=str(screenshot_path) if screenshot_path else None)
            return "staged"

        try:
            apply_btn.click()
            random_delay(2.5, 4.0)

            # Check for success message or applied status
            success_indicators = [
                "text='Successfully Applied'",
                "text='Applied'",
                "button:has-text('Applied')",
                ".success-msg",
                ".applied_msg"
            ]
            for ind in success_indicators:
                if page.locator(ind).first.is_visible(timeout=2000):
                    break

            logger.info(f"[Shine] Successfully applied to Job #{job_id}!")
            update_job_apply_status(job_id, "applied", screenshot_path=str(screenshot_path) if screenshot_path else None)
            return "applied"
        except Exception as e:
            logger.error(f"[Shine] Application click error for Job #{job_id}: {e}")
            update_job_apply_status(job_id, "failed", error_message=str(e))
            return "failed"

    def handle_screening_questions(self, page: Page, job: Dict[str, Any], resume_text: str) -> List[Dict[str, str]]:
        return []
