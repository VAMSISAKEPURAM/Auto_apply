import sys
import argparse
from playwright.sync_api import sync_playwright
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from .utils import load_settings, setup_logger
from .db import init_db, get_summary_stats
from .auth import login_interactive, ensure_authenticated_context, is_session_valid
from .scraper import run_scraper
from .ranker import run_ranker
from .applier import run_applier

logger = setup_logger("main")
console = Console()


def show_banner():
    console.print(Panel.fit(
        "[bold cyan]Naukri Job-Search & Apply Agent[/bold cyan]\n"
        "[italic white]Stealth Automation • Groq LLM Scoring • Human Approval Checkpoint[/italic white]",
        border_style="cyan"
    ))


def cmd_init():
    """Initialize database tables."""
    init_db()
    console.print("[green]Database initialized successfully.[/green]")


def cmd_login():
    """Launch interactive browser for manual login and session persistence."""
    init_db()
    with sync_playwright() as p:
        success = login_interactive(p, headless=False)
        if success:
            console.print("[bold green]Login completed and session successfully saved to data/session.json[/bold green]")
        else:
            console.print("[bold red]Login was not completed.[/bold red]")


def cmd_scrape():
    """Scrape job postings from Naukri using configured keywords and locations."""
    init_db()
    settings = load_settings()
    headless = settings.get("execution", {}).get("headless", False)

    console.print("[cyan]Starting scraper...[/cyan]")
    with sync_playwright() as p:
        browser, context = ensure_authenticated_context(p, headless=headless)
        page = context.new_page()
        try:
            stats = run_scraper(page, settings)
            console.print(f"[bold green]Scrape finished! {stats['found']} listings found, {stats['new']} new jobs added to database.[/bold green]")
        finally:
            browser.close()


def cmd_rank():
    """Score unscored jobs in the DB using Groq LLM."""
    init_db()
    console.print("[cyan]Starting Groq LLM Fit Scoring...[/cyan]")
    stats = run_ranker()
    console.print(f"[bold green]Ranking finished! {stats['processed']} scored, {stats['qualified']} qualified for apply stage.[/bold green]")


def cmd_apply():
    """Run approval-gated application pipeline."""
    init_db()
    settings = load_settings()
    headless = settings.get("execution", {}).get("headless", False)

    console.print("[cyan]Starting application pipeline...[/cyan]")
    with sync_playwright() as p:
        browser, context = ensure_authenticated_context(p, headless=headless)
        page = context.new_page()
        try:
            stats = run_applier(page)
            console.print(f"[bold green]Application run finished! Results: {stats}[/bold green]")
        finally:
            browser.close()


def cmd_run_all():
    """Execute end-to-end pipeline: Scrape -> Rank -> Apply."""
    init_db()
    settings = load_settings()
    headless = settings.get("execution", {}).get("headless", False)

    console.print("[bold magenta]Starting Full Agent Pipeline (Scrape -> Rank -> Apply)...[/bold magenta]")
    
    with sync_playwright() as p:
        browser, context = ensure_authenticated_context(p, headless=headless)
        page = context.new_page()
        try:
            # 1. Scrape
            console.print("\n[bold cyan]Step 1/3: Scraping Jobs[/bold cyan]")
            scrape_stats = run_scraper(page, settings)

            # 2. Rank
            console.print("\n[bold cyan]Step 2/3: LLM Relevance Ranking[/bold cyan]")
            rank_stats = run_ranker()

            # 3. Apply
            console.print("\n[bold cyan]Step 3/3: Staged Apply Pipeline[/bold cyan]")
            apply_stats = run_applier(page)

            console.print("\n[bold green]End-to-End Pipeline Complete![/bold green]")
            cmd_summary()
        finally:
            browser.close()


def cmd_summary():
    """Display current database summary statistics."""
    init_db()
    stats = get_summary_stats()
    
    table = Table(title="Naukri Agent Status Summary", header_style="bold cyan")
    table.add_column("Status Lifecycle", style="bold")
    table.add_column("Count", justify="right", style="green")

    for status, count in stats.items():
        if status != "total":
            table.add_row(status.capitalize(), str(count))

    table.add_section()
    table.add_row("Total Jobs Tracked", str(stats.get("total", 0)), style="bold yellow")
    
    console.print(table)


def cmd_health():
    """Quick selector and connectivity health check on Naukri."""
    init_db()
    settings = load_settings()
    console.print("[cyan]Running Naukri Selector Health Check...[/cyan]")
    
    with sync_playwright() as p:
        browser, context = ensure_authenticated_context(p, headless=False)
        page = context.new_page()
        try:
            page.goto("https://www.naukri.com/python-developer-jobs", wait_until="domcontentloaded", timeout=25000)
            
            checks = {
                "Job Tuples": [".srp-jobtuple-wrapper", ".cust-job-tuple", "article.jobTuple", "div[data-job-id]"],
                "Job Title Link": ["a.title", ".title a"],
                "Company Name": ["a.comp-name", ".comp-name"],
                "Experience Tag": [".exp-wrap", ".exp"],
                "Pagination Next": ["a:has-text('Next')", ".pagination a"]
            }

            table = Table(title="Naukri Selector Health Status", header_style="bold cyan")
            table.add_column("Component", style="bold")
            table.add_column("Status", style="bold")
            table.add_column("Matching Selector", style="dim")

            for name, selectors in checks.items():
                found_selector = None
                for sel in selectors:
                    if page.locator(sel).first.is_visible(timeout=3000):
                        found_selector = sel
                        break
                
                if found_selector:
                    table.add_row(name, "[green]PASSED[/green]", found_selector)
                else:
                    table.add_row(name, "[red]FAILED[/red]", "None matched")

            console.print(table)
        finally:
            browser.close()


def cmd_applied():
    """Display all jobs successfully applied to with timestamps and details."""
    init_db()
    from .db import get_db_connection
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, title, company, location, relevance_score, applied_at, screenshot_path 
            FROM jobs 
            WHERE status = 'applied' 
            ORDER BY applied_at DESC, id DESC
        """)
        rows = cursor.fetchall()

    if not rows:
        console.print("[yellow]No jobs marked as 'applied' yet.[/yellow]")
        console.print("[dim]Tip: Run 'python -m src.main apply' to start applying to qualified jobs.[/dim]")
        return

    table = Table(title=f"Successfully Applied Jobs ({len(rows)} Total)", header_style="bold green")
    table.add_column("ID", justify="center", style="cyan", width=5)
    table.add_column("Job Title", style="bold white")
    table.add_column("Company", style="white")
    table.add_column("Location", style="white")
    table.add_column("Score", justify="center", style="bold green", width=7)
    table.add_column("Applied At", style="dim", width=20)

    for r in rows:
        table.add_row(
            str(r["id"]),
            str(r["title"]),
            str(r["company"]),
            str(r["location"]),
            f"{r['relevance_score']}/100",
            str(r["applied_at"] or "Recorded")
        )

    console.print(table)


def cmd_export():
    """Export all applied and tracked jobs into an Excel workbook."""
    init_db()
    from .exporter import export_jobs_to_excel
    path = export_jobs_to_excel()
    console.print(f"[bold green]Excel file generated successfully:[/bold green] [underline white]{path}[/underline white]")


def cmd_schedule():
    """Start continuous automated hourly agent daemon."""
    init_db()
    settings = load_settings()
    interval = settings.get("scheduler", {}).get("interval_hours", 1)
    from .scheduler import start_scheduler_daemon
    start_scheduler_daemon(interval_hours=interval)


def main():
    show_banner()
    parser = argparse.ArgumentParser(description="Naukri Job Search & Apply Agent")
    parser.add_argument(
        "command",
        choices=["init", "login", "scrape", "rank", "apply", "run", "summary", "health", "applied", "export", "schedule"],
        help="Command to execute"
    )

    args = parser.parse_args()

    if args.command == "init":
        cmd_init()
    elif args.command == "login":
        cmd_login()
    elif args.command == "scrape":
        cmd_scrape()
    elif args.command == "rank":
        cmd_rank()
    elif args.command == "apply":
        cmd_apply()
    elif args.command == "applied":
        cmd_applied()
    elif args.command == "export":
        cmd_export()
    elif args.command == "schedule":
        cmd_schedule()
    elif args.command == "run":
        cmd_run_all()
    elif args.command == "summary":
        cmd_summary()
    elif args.command == "health":
        cmd_health()


if __name__ == "__main__":
    main()
