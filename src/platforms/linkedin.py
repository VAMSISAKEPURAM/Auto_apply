import re
import urllib.parse
from datetime import datetime
from typing import List, Dict, Any, Optional
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from .base import JobPlatform
from ..utils import setup_logger, random_delay, SCREENSHOTS_DIR
from ..db import upsert_job, is_job_already_applied, update_job_apply_status
from ..filters import build_linkedin_search_url, filter_job_card

logger = setup_logger("platform.linkedin")


def construct_linkedin_search_url(
    keyword: str, 
    location: str = "", 
    experience_years: int = 1, 
    job_age_days: int = 30
) -> str:
    """
    Construct LinkedIn search URL with Easy Apply, experience, city, and freshness filters.
    """
    return build_linkedin_search_url(
        keyword=keyword, 
        location=location, 
        experience_years=experience_years, 
        job_age_days=job_age_days,
        easy_apply_only=True
    )


def check_for_security_checkpoint(page: Page) -> bool:
    """Check if LinkedIn has triggered a verification or CAPTCHA challenge."""
    current_url = page.url.lower()
    if "checkpoint/challenge" in current_url or "security-check" in current_url:
        logger.warning("[LinkedIn] Security checkpoint/challenge detected. Halting LinkedIn automation for safety.")
        return True
    
    challenge_indicators = [
        "#captcha-internal",
        "div[data-control-name='challenge']",
        "text='Verify it is you'",
        "text='Security Verification'"
    ]
    for ind in challenge_indicators:
        if page.locator(ind).first.is_visible(timeout=1000):
            logger.warning(f"[LinkedIn] Challenge indicator '{ind}' visible. Halting.")
            return True
            
    return False


class LinkedInPlatform(JobPlatform):
    """
    LinkedIn platform adapter with Easy Apply automation, security safety checks, and Groq LLM integration.
    """
    name: str = "linkedin"
    display_name: str = "LinkedIn"

    def search_jobs(self, page: Page, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Scrape Easy Apply job postings from LinkedIn with full filtering."""
        search_config = settings.get("search", {})
        filters_config = settings.get("filters", {})
        keywords = search_config.get("keywords", ["Python Developer"])
        locations = search_config.get("locations", ["Bengaluru", "Remote"])
        exp_years = search_config.get("experience_years", 1)
        job_age_days = filters_config.get("max_job_age_days", 30)

        stats = {"found": 0, "new": 0, "skipped": 0, "filtered": 0}

        for keyword in keywords:
            for location in locations:
                search_url = construct_linkedin_search_url(
                    keyword=keyword, 
                    location=location, 
                    experience_years=exp_years, 
                    job_age_days=job_age_days
                )
                logger.info(f"[LinkedIn] Searching: '{keyword}' in '{location}' (Exp: {exp_years} Yrs) -> {search_url}")

                try:
                    page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                    random_delay(3.0, 5.0)
                except Exception as e:
                    logger.error(f"[LinkedIn] Search navigation failed for {keyword}: {e}")
                    continue

                if check_for_security_checkpoint(page):
                    return stats

                # Smoothly scroll search results list
                for _ in range(3):
                    try:
                        page.evaluate("""
                            const container = document.querySelector('.jobs-search-results-list') || window;
                            container.scrollBy({ top: 800, behavior: 'smooth' });
                        """)
                        random_delay(1.5, 2.5)
                    except Exception:
                        pass

                # Locate job cards
                card_selectors = [
                    "div.job-card-container",
                    "li.jobs-search-results__list-item",
                    "div[data-job-id]",
                    ".jobs-search-results__list li"
                ]

                job_cards = []
                for sel in card_selectors:
                    cards = page.locator(sel).all()
                    if cards:
                        job_cards = cards
                        break

                logger.info(f"[LinkedIn] Found {len(job_cards)} job cards on current search page.")
                stats["found"] += len(job_cards)

                for card in job_cards:
                    try:
                        # Extract title and URL
                        title_el = card.locator("a.job-card-list__title, a.job-card-container__link, a[href*='/jobs/view/']").first
                        if title_el.count() == 0:
                            continue

                        title = title_el.inner_text().strip()
                        raw_href = title_el.get_attribute("href") or ""
                        
                        # Clean LinkedIn job URL
                        job_id_match = re.search(r"/view/(\d+)", raw_href) or re.search(r"currentJobId=(\d+)", raw_href)
                        if job_id_match:
                            clean_url = f"https://www.linkedin.com/jobs/view/{job_id_match.group(1)}/"
                        else:
                            clean_url = raw_href.split("?")[0] if raw_href else ""

                        if not clean_url:
                            continue

                        # Extract company
                        company_el = card.locator(".job-card-container__company-name, .artdeco-entity-lockup__subtitle, [class*='company-name']").first
                        company = company_el.inner_text().strip() if company_el.count() > 0 else ""

                        # Extract location
                        loc_el = card.locator(".job-card-container__metadata-item, .artdeco-entity-lockup__caption").first
                        loc_text = loc_el.inner_text().strip() if loc_el.count() > 0 else location

                        job_data = {
                            "url": clean_url,
                            "title": title,
                            "company": company,
                            "location": loc_text,
                            "experience": f"{exp_years} Yrs",
                            "skills": keyword,
                            "posted_date": "Recently",
                            "apply_type": "easy_apply",
                            "description": f"LinkedIn Easy Apply listing for {title} at {company}",
                            "platform": "linkedin"
                        }

                        # Apply Experience, City & Role Filters
                        passed, reason = filter_job_card(job_data, settings)
                        if not passed:
                            stats["filtered"] += 1
                            logger.info(f"[LinkedIn Filter] ✗ Discarded: '{title}' at '{company}' (Reason: {reason})")
                            continue

                        inserted = upsert_job(job_data)
                        if inserted:
                            stats["new"] += 1
                            logger.info(f"[LinkedIn Filter] ✓ Added Job: {title} | {company} | {loc_text} ({clean_url})")
                        else:
                            stats["skipped"] += 1

                    except Exception as e:
                        logger.debug(f"[LinkedIn] Notice parsing card: {e}")

                random_delay(2.5, 4.5)

        return stats

    def apply(self, page: Page, job: Dict[str, Any], settings: Dict[str, Any], resume_text: str) -> str:
        """Process LinkedIn Easy Apply application flow."""
        url = job.get("url", "")
        job_id = job.get("id")
        dry_run = settings.get("execution", {}).get("dry_run", True)

        logger.info(f"[LinkedIn] Opening Job #{job_id}: {job.get('title')} at {job.get('company')}")
        
        # Deduplication check
        if is_job_already_applied("linkedin", url):
            logger.info(f"[LinkedIn] Job already applied in database: {url}")
            return "already applied"

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            random_delay(2.5, 4.5)
        except Exception as e:
            logger.error(f"[LinkedIn] Failed to open job page: {e}")
            update_job_apply_status(job_id, "failed", error_message=f"Navigation error: {e}")
            return "failed"

        if check_for_security_checkpoint(page):
            update_job_apply_status(job_id, "failed", error_message="Security checkpoint encountered")
            return "failed"

        # Check if already applied on page
        already_applied_el = page.locator(".jobs-applied-banner, span:has-text('Applied'), button:has-text('Applied')").first
        if already_applied_el.is_visible(timeout=2000):
            logger.info("[LinkedIn] Job already shows as applied on LinkedIn.")
            update_job_apply_status(job_id, "already applied", error_message="Already applied on LinkedIn")
            return "already applied"

        # Check for Easy Apply button
        easy_apply_btn = page.locator(
            "button.jobs-apply-button:has-text('Easy Apply'), "
            "button:has-text('Easy Apply'), "
            "button[aria-label*='Easy Apply'], "
            ".jobs-s-apply button:has-text('Easy Apply'), "
            "a:has-text('Easy Apply')"
        ).first
        
        if not easy_apply_btn.is_visible(timeout=3000):
            # Check if external apply button exists
            external_btn = page.locator(
                "button.jobs-apply-button:has-text('Apply'), "
                "a:has-text('Apply on company website'), "
                "a:has-text('Apply'), "
                "button:has-text('Apply'), "
                "[aria-label*='Apply on']"
            ).first
            if external_btn.is_visible(timeout=2000):
                logger.info("[LinkedIn] Job requires external apply. Marking as External Redirect.")
                update_job_apply_status(job_id, "external redirect", error_message="External company site apply")
                return "external redirect"

            logger.warning("[LinkedIn] No Easy Apply button located.")
            update_job_apply_status(job_id, "failed", error_message="Easy Apply button not found")
            return "failed"

        # Click Easy Apply
        try:
            try:
                easy_apply_btn.click(timeout=5000)
            except Exception:
                page.evaluate("(el) => el.click()", easy_apply_btn.element_handle())
            random_delay(2.0, 3.5)
        except Exception as e:
            logger.error(f"[LinkedIn] Error clicking Easy Apply: {e}")
            update_job_apply_status(job_id, "failed", error_message=f"Easy apply click failed: {e}")
            return "failed"

        # Modal step loop (Contact info -> Resume -> Questions -> Review)
        modal = page.locator("dialog, [role='dialog'], div.jobs-easy-apply-modal, div[data-test-modal], div.artdeco-modal").first
        if not modal.is_visible(timeout=4000):
            logger.warning("[LinkedIn] Easy Apply modal did not open.")
            update_job_apply_status(job_id, "failed", error_message="Modal not detected")
            return "failed"

        qa_list = self.handle_screening_questions(page, job, resume_text)
        qa_str = "\n".join([f"Q: {item['question']} -> A: {item['answer']}" for item in qa_list]) if qa_list else "None"

        # Step through modal pages
        for step in range(5):
            # Check for Submit application button (Review step)
            submit_btn = page.locator("button:has-text('Submit application'), button[aria-label='Submit application'], button:has-text('Submit')").first
            if submit_btn.is_visible(timeout=1500):
                logger.info("[LinkedIn] Reached application Review / Submit step.")
                break

            # Handle step questions
            self.handle_screening_questions(page, job, resume_text)

            # Look for Next / Review button
            next_btn = page.locator("button:has-text('Next'), button:has-text('Review'), button[aria-label='Continue to next step']").first
            if next_btn.is_visible(timeout=1500):
                next_btn.click()
                random_delay(1.5, 2.5)
            else:
                break

        # Capture screenshot of staged modal
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        screenshot_path = SCREENSHOTS_DIR / f"linkedin_staged_{job_id}_{timestamp}.png"
        try:
            page.screenshot(path=str(screenshot_path))
        except Exception:
            screenshot_path = None

        if dry_run:
            logger.info(f"[LinkedIn] [DRY-RUN] Staged application for job #{job_id}. Dismissing modal.")
            self._dismiss_modal(page)
            update_job_apply_status(
                job_id, 
                status="staged", 
                screening_qa=qa_str, 
                screenshot_path=str(screenshot_path) if screenshot_path else None
            )
            return "staged"

        # Live Submit
        submit_btn = page.locator("button:has-text('Submit application'), button[aria-label='Submit application'], button:has-text('Submit')").first
        if submit_btn.is_visible(timeout=2000):
            submit_btn.click()
            random_delay(3.0, 5.0)

            # Close confirmation dialog / Done button
            done_btn = page.locator("button:has-text('Done'), button[aria-label='Dismiss']").first
            if done_btn.is_visible(timeout=3000):
                done_btn.click()

            logger.info(f"[LinkedIn] Successfully submitted application for job #{job_id}!")
            update_job_apply_status(
                job_id, 
                status="applied", 
                screening_qa=qa_str, 
                screenshot_path=str(screenshot_path) if screenshot_path else None
            )
            return "applied"
        else:
            self._dismiss_modal(page)
            update_job_apply_status(job_id, "failed", error_message="Submit button not reached")
            return "failed"

    def handle_screening_questions(self, page: Page, job: Dict[str, Any], resume_text: str) -> List[Dict[str, str]]:
        """Detect and fill form questions inside LinkedIn Easy Apply modal."""
        qa_list = []
        try:
            # Handle text input fields
            inputs = page.locator("dialog input[type='text']:visible, dialog textarea:visible, [role='dialog'] input[type='text']:visible, div.jobs-easy-apply-modal input[type='text']:visible, div.jobs-easy-apply-modal textarea:visible").all()
            for field in inputs:
                val = field.input_value().strip()
                if not val:
                    # Provide standard default for numeric or experience questions
                    field.fill("3")
                    random_delay(0.3, 0.7)

            # Handle radio buttons (e.g. 'Yes' / 'No' / Work authorization)
            radios = page.locator("dialog input[type='radio']:visible, [role='dialog'] input[type='radio']:visible, div.jobs-easy-apply-modal input[type='radio']:visible").all()
            for radio in radios:
                label_text = radio.evaluate("el => el.parentElement ? el.parentElement.innerText : ''").strip().lower()
                if "yes" in label_text or "agree" in label_text:
                    if not radio.is_checked():
                        radio.check(force=True)
                        random_delay(0.3, 0.6)

        except Exception as e:
            logger.debug(f"[LinkedIn] Notice handling questions: {e}")

        return qa_list

    def _dismiss_modal(self, page: Page):
        """Safely close and discard LinkedIn Easy Apply modal."""
        try:
            dismiss_btn = page.locator("button[aria-label='Dismiss'], dialog button[aria-label='Dismiss'], button.artdeco-modal__dismiss, button:has-text('Discard')").first
            if dismiss_btn.is_visible(timeout=1500):
                dismiss_btn.click()
                random_delay(0.5, 1.0)
                discard_confirm = page.locator("button[data-control-name='discard_application_confirm_btn'], button:has-text('Discard'), button:has-text('Confirm')").first
                if discard_confirm.is_visible(timeout=1500):
                    discard_confirm.click()
        except Exception:
            pass
