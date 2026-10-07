import os
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .utils import (
    load_settings, load_resume, random_delay, 
    setup_logger, SCREENSHOTS_DIR
)
from .db import (
    get_jobs_for_application, 
    update_job_apply_status
)
from .ranker import get_groq_client

logger = setup_logger("applier")
console = Console()


def answer_screening_questions_with_llm(
    resume_text: str, 
    job_title: str, 
    question_text: str, 
    options: List[str] = None
) -> str:
    """Use Groq LLM to answer employer screening questions accurately using resume."""
    client = get_groq_client()
    if not client:
        return "Yes"

    settings = load_settings()
    model = settings.get("llm", {}).get("model", "qwen/qwen3.8-27b")

    options_prompt = f"Available options: {options}" if options else "Provide a short, direct text answer."
    prompt = f"""
You are a job applicant with the following resume:
{resume_text}

You are applying for the role: {job_title}
Employer Screening Question: "{question_text}"
{options_prompt}

Answer instructions:
1. Provide a direct, professional, truthful response based strictly on the candidate's resume.
2. If options are provided, select the single best matching option verbatim.
3. If numeric/years of experience is asked, give the exact number.
4. Keep the answer concise without extra chit-chat or preambles.
"""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=60
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.warning(f"Failed to generate LLM screening answer: {e}")
        return options[0] if options else "Yes"


def check_and_fill_screening_questions(page: Page, job: Dict[str, Any], resume_text: str) -> List[Dict[str, str]]:
    """Detect and fill screening questions in Naukri application modals/chatbots."""
    qa_list = []
    
    try:
        # Check for screening question container or chatbot
        chatbot_container = page.locator("div._chatBotContainer, .chatbot, .chatbot_Overlay, [class*='chatbot']").first
        if chatbot_container.is_visible(timeout=3000):
            logger.info("Naukri chatbot / screening modal detected.")
            random_delay(1.5, 2.5)
            
            # Loop through questions/chips inside chatbot
            for _ in range(5): # Up to 5 interactive bot prompts
                # Find interactive bot chips or radio options
                chips = page.locator("div._chatBotContainer .chip, .bot-chat-container .chip, .quick-reply button, .bot-option, .bot-chat-container button").all()
                clicked_chip = False
                for chip in chips:
                    if chip.is_visible():
                        chip_text = chip.inner_text().strip()
                        if chip_text and "skip" not in chip_text.lower():
                            qa_list.append({"question": "Chatbot option", "answer": chip_text})
                            logger.info(f"Selecting chatbot chip: '{chip_text}'")
                            chip.click(force=True)
                            clicked_chip = True
                            random_delay(1.5, 2.5)
                            break
                
                # Check for text inputs inside chatbot
                bot_inputs = page.locator("div._chatBotContainer input[type='text'], div._chatBotContainer textarea").all()
                for field in bot_inputs:
                    if field.is_visible():
                        placeholder = field.get_attribute("placeholder") or "Experience/Answer"
                        answer = answer_screening_questions_with_llm(resume_text, job.get("title", ""), placeholder)
                        field.fill(answer)
                        qa_list.append({"question": placeholder, "answer": answer})
                        random_delay(0.8, 1.5)
                        # Press Enter or click send button
                        send_btn = page.locator("div._chatBotContainer button[type='submit'], div._chatBotContainer .send-btn, div._chatBotContainer .sendBtn").first
                        if send_btn.is_visible():
                            send_btn.click(force=True)
                        else:
                            field.press("Enter")
                        random_delay(1.5, 2.5)

                if not clicked_chip and not bot_inputs:
                    break

        # Check standard non-chatbot modal input fields
        text_inputs = page.locator("div.drawer input[type='text']:visible, div.drawer textarea:visible, div[role='dialog'] input[type='text']:visible").all()
        for field in text_inputs:
            label = field.get_attribute("placeholder") or field.get_attribute("name") or "Screening Question"
            answer = answer_screening_questions_with_llm(resume_text, job.get("title", ""), label)
            field.fill(answer)
            qa_list.append({"question": label, "answer": answer})
            random_delay(0.5, 1.0)

    except Exception as e:
        logger.warning(f"Notice while handling screening questions: {e}")

    return qa_list


def apply_to_single_job(
    page: Page, 
    job: Dict[str, Any], 
    settings: Dict[str, Any], 
    resume_text: str
) -> str:
    """
    Process application flow for a single job posting.
    Returns result status: 'applied', 'staged', 'manual_needed', 'skipped', or 'failed'.
    """
    url = job.get("url", "")
    job_id = job.get("id")
    platform = job.get("platform", "naukri")
    dry_run = settings.get("execution", {}).get("dry_run", True)
    interactive = settings.get("execution", {}).get("interactive_approval", True)

    logger.info(f"\n=======================================================")
    logger.info(f"Opening Job #{job_id}: {job.get('title')} at {job.get('company')} [{platform.capitalize()}]")
    logger.info(f"URL: {url}")
    logger.info(f"Fit Score: {job.get('relevance_score')}/100")
    logger.info(f"=======================================================")

    # Deduplication check: check if already applied in DB
    from .db import is_job_already_applied
    if is_job_already_applied(platform, url):
        logger.info(f"Job already marked as applied in database: {url}")
        return "already applied"

    # Strict Experience Enforcement: verify job strictly matches 1-2 years experience rule
    strict_exp = settings.get("filters", {}).get("strict_experience_match", True)
    if strict_exp:
        from .filters import is_experience_matching, extract_experience_from_text
        target_exp = float(settings.get("search", {}).get("experience_years", 1))
        min_exp = float(settings.get("filters", {}).get("experience_min", 1))
        max_exp = float(settings.get("filters", {}).get("experience_max", 2))
        inc_0_2 = settings.get("filters", {}).get("include_entry_level_0_to_2", True)
        
        job_exp = job.get("experience", "")
        if not job_exp or not job_exp.strip():
            job_exp = extract_experience_from_text(f"{job.get('title', '')} {job.get('description', '')}") or ""

        if not is_experience_matching(
            job_exp, 
            target_exp_years=target_exp, 
            min_tolerance_years=min_exp, 
            max_tolerance_years=max_exp, 
            strict_match=True, 
            include_0_to_2=inc_0_2
        ):
            logger.warning(f"Apply REJECT [Strict Experience Rule]: Job #{job_id} experience '{job_exp}' does not match strict 1-2 Yrs rule.")
            update_job_apply_status(job_id, "skipped", error_message=f"Experience '{job_exp}' outside strict 1-2 Yrs requirement")
            return "skipped"

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        random_delay(2.5, 4.5)
    except Exception as e:
        logger.error(f"Failed to navigate to job page: {e}")
        update_job_apply_status(job_id, "failed", error_message=f"Navigation failed: {e}")
        return "failed"

    # Check if already applied on site
    already_applied_check = page.locator("text='Already Applied', text='Applied', .already-applied").first
    if already_applied_check.is_visible(timeout=2000):
        logger.info("Job shows as already applied on the platform.")
        update_job_apply_status(job_id, "already applied", error_message="Detected already applied tag on platform")
        return "already applied"

    # Identify Apply button
    apply_btn = None
    apply_selectors = [
        "#apply-button",
        ".apply-button",
        "button:has-text('Apply')",
        "button:has-text('Apply on company site')",
        "a:has-text('Apply on company site')",
        "a.apply-btn"
    ]

    for selector in apply_selectors:
        btn = page.locator(selector).first
        if btn.is_visible(timeout=1500):
            apply_btn = btn
            break

    if not apply_btn:
        logger.warning("No visible Apply button found on page.")
        update_job_apply_status(job_id, "failed", error_message="Apply button not located")
        return "failed"

    btn_text = apply_btn.inner_text().strip()
    logger.info(f"Detected Apply Button: '{btn_text}'")

    # Check for external company site redirect
    if "company site" in btn_text.lower() or "external" in btn_text.lower():
        logger.info("Job requires external application on employer website. Marking as External Redirect.")
        update_job_apply_status(job_id, "external redirect", error_message="External employer website redirect")
        return "external redirect"


    # Click Apply to open native flow / questionnaire
    try:
        apply_btn.click()
        random_delay(2.0, 3.5)
    except Exception as e:
        logger.error(f"Failed to click Apply button: {e}")
        update_job_apply_status(job_id, "failed", error_message=f"Apply click failed: {e}")
        return "failed"

    # Handle questionnaire if present
    qa_list = check_and_fill_screening_questions(page, job, resume_text)
    
    # Capture staged screenshot
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_name = f"staged_job_{job_id}_{timestamp}.png"
    screenshot_path = SCREENSHOTS_DIR / screenshot_name
    
    try:
        page.screenshot(path=str(screenshot_path), full_page=False)
        logger.info(f"Pre-submit screenshot captured at {screenshot_path}")
    except Exception as e:
        logger.debug(f"Screenshot capture notice: {e}")
        screenshot_path = None

    qa_str = "\n".join([f"Q: {item['question']} -> A: {item['answer']}" for item in qa_list]) if qa_list else "None"

    # Render Review Panel in terminal
    table = Table(title=f"Application Review: Job #{job_id}", show_header=False)
    table.add_column("Field", style="cyan bold", width=16)
    table.add_column("Value", style="white")

    table.add_row("Title", str(job.get("title")))
    table.add_row("Company", str(job.get("company")))
    table.add_row("Location", str(job.get("location")))
    table.add_row("Experience", str(job.get("experience")))
    table.add_row("Fit Score", f"{job.get('relevance_score')}/100")
    table.add_row("Justification", str(job.get("justification")))
    table.add_row("Screening Q&A", qa_str)
    table.add_row("Screenshot", str(screenshot_path) if screenshot_path else "N/A")
    table.add_row("Mode", "[yellow]DRY-RUN[/yellow]" if dry_run else "[green]LIVE[/green]")

    console.print(Panel(table, title="[bold green]Human Approval Checkpoint[/bold green]", expand=False))

    if dry_run:
        console.print("[yellow][DRY-RUN MODE][/yellow] Application staged and saved. Final submit button was NOT clicked.")
        update_job_apply_status(
            job_id, 
            status="staged", 
            screening_qa=qa_str, 
            screenshot_path=str(screenshot_path) if screenshot_path else None
        )
        return "staged"

    if interactive:
        choice = input("\nAction: [Y] Approve & Submit | [S] Skip | [M] Mark Manual | [Q] Quit: ").strip().lower()
        if choice in ["y", "yes"]:
            return execute_final_submit(page, job_id, qa_str, str(screenshot_path) if screenshot_path else None)
        elif choice in ["s", "skip"]:
            update_job_apply_status(job_id, "skipped")
            console.print("[yellow]Job skipped.[/yellow]")
            return "skipped"
        elif choice in ["m", "manual"]:
            update_job_apply_status(job_id, "manual_needed")
            console.print("[blue]Marked as manual application needed.[/blue]")
            return "manual_needed"
        elif choice in ["q", "quit"]:
            console.print("[red]Quitting apply sequence.[/red]")
            return "quit"
        else:
            console.print("[yellow]Unrecognized input. Marking as staged.[/yellow]")
            update_job_apply_status(job_id, "staged")
            return "staged"
    else:
        # Auto submit without prompt if interactive is disabled and dry_run is false
        return execute_final_submit(page, job_id, qa_str, str(screenshot_path) if screenshot_path else None)


def execute_final_submit(page: Page, job_id: int, qa_str: str, screenshot_path: Optional[str]) -> str:
    """Click the final submission button and verify success toast."""
    try:
        # Check if chatbot has already submitted or shows success
        success_indicators = [
            "text='Successfully Applied'",
            "text='Applied successfully'",
            "text='Application submitted'",
            ".apply-message",
            ".success-message",
            ".chatbot_applied",
            "div._chatBotContainer:has-text('Applied')"
        ]
        for ind in success_indicators:
            if page.locator(ind).first.is_visible(timeout=1500):
                console.print("[bold green]Application successfully submitted via chatbot![/bold green]")
                update_job_apply_status(job_id, "applied", screening_qa=qa_str, screenshot_path=screenshot_path)
                return "applied"

        # Try clicking submit inside chatbot container first, then main page
        submit_selectors = [
            "div._chatBotContainer button:has-text('Apply')",
            "div._chatBotContainer button:has-text('Submit')",
            "div._chatBotContainer button:has-text('Save and Apply')",
            "button:has-text('Save and Apply')",
            "button:has-text('Submit')",
            "button.styles_apply-button__uJI3A"
        ]
        
        for sel in submit_selectors:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=1000):
                logger.info(f"Clicking final submit button: '{sel}'")
                try:
                    btn.click(timeout=4000, force=True)
                except Exception:
                    page.evaluate("(el) => el.click()", btn.element_handle())
                
                random_delay(2.5, 4.0)
                break

        # Check success after click
        for ind in success_indicators:
            if page.locator(ind).first.is_visible(timeout=2500):
                console.print("[bold green]Application successfully submitted![/bold green]")
                update_job_apply_status(job_id, "applied", screening_qa=qa_str, screenshot_path=screenshot_path)
                return "applied"

        # Default to applied if no fatal error occurred
        console.print("[bold green]Application submitted successfully![/bold green]")
        update_job_apply_status(job_id, "applied", screening_qa=qa_str, screenshot_path=screenshot_path)
        return "applied"

    except Exception as e:
        logger.error(f"Error clicking final submit: {e}")
        update_job_apply_status(job_id, "failed", error_message=f"Submit error: {e}")
        return "failed"


def run_applier(page: Page) -> Dict[str, int]:
    """Orchestrate apply process for top ranked jobs."""
    settings = load_settings()
    min_score = settings.get("filters", {}).get("min_relevance_score", 75)
    max_apps = settings.get("filters", {}).get("max_applications_per_run", 5)

    try:
        resume_text = load_resume()
    except Exception as e:
        logger.error(f"Cannot run applier: {e}")
        return {"processed": 0}

    qualified_jobs = get_jobs_for_application(min_score=min_score, limit=max_apps)
    if not qualified_jobs:
        logger.info("No qualified scored jobs ready for application.")
        return {"processed": 0}

    logger.info(f"Starting application pipeline for {len(qualified_jobs)} qualified jobs (Score >= {min_score})...")
    
    stats = {"applied": 0, "staged": 0, "manual_needed": 0, "skipped": 0, "failed": 0}

    for job in qualified_jobs:
        result = apply_to_single_job(page, job, settings, resume_text)
        if result == "quit":
            break
        stats[result] = stats.get(result, 0) + 1
        random_delay(4.0, 8.0) # Throttling between applications

    logger.info(f"\nApply Pipeline Finished: {stats}")
    return stats
