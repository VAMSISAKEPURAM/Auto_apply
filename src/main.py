import sys
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import argparse
from typing import Optional, List
from playwright.sync_api import sync_playwright
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from .utils import load_settings, setup_logger
from .db import init_db, get_summary_stats
from .platforms import get_enabled_platforms, get_platform, PLATFORM_REGISTRY
from .ranker import run_ranker

logger = setup_logger("main")
console = Console(highlight=False)


def show_banner():
    console.print(Panel.fit(
        "[bold cyan]Multi-Platform Job-Search & Apply Agent[/bold cyan]\n"
        "[italic white]Stealth Automation - Multi-Platform Adapters - Groq LLM Scoring[/italic white]",
        border_style="cyan"
    ))


def parse_site_list(sites_arg: Optional[str]) -> Optional[List[str]]:
    """Parse comma-separated sites string into list of strings."""
    if not sites_arg:
        return None
    return [s.strip().lower() for s in sites_arg.split(",") if s.strip()]


def cmd_init():
    """Initialize database tables and schema migrations."""
    init_db()
    console.print("[green]Database and platform schema initialized successfully.[/green]")


def cmd_login(sites: Optional[List[str]] = None):
    """Launch interactive browser for manual login and session persistence across enabled platforms."""
    init_db()
    settings = load_settings()
    platforms = get_enabled_platforms(settings, requested_sites=sites)
    
    if not platforms:
        console.print("[yellow]No valid platforms selected for login.[/yellow]")
        return

    with sync_playwright() as p:
        for platform in platforms:
            console.print(f"\n[bold cyan]Starting login for {platform.display_name}...[/bold cyan]")
            try:
                success = platform.login_interactive(p, headless=False)
                if success:
                    console.print(f"[bold green]Session successfully verified & saved for {platform.display_name}![/bold green]")
                else:
                    console.print(f"[bold red]Login was not completed for {platform.display_name}.[/bold red]")
            except Exception as e:
                logger.error(f"Error during login on {platform.display_name}: {e}", exc_info=True)
                console.print(f"[red]Failed login for {platform.display_name}: {e}[/red]")


def cmd_scrape(sites: Optional[List[str]] = None):
    """Scrape job postings from enabled platforms using configured keywords and locations."""
    init_db()
    settings = load_settings()
    headless = settings.get("execution", {}).get("headless", False)
    platforms = get_enabled_platforms(settings, requested_sites=sites)

    if not platforms:
        console.print("[yellow]No active platforms configured or found.[/yellow]")
        return

    console.print(f"[cyan]Active platforms for scraping: {[p.name for p in platforms]}[/cyan]")
    
    with sync_playwright() as p:
        for platform in platforms:
            console.print(f"\n[bold cyan]== Scraping {platform.display_name} ==[/bold cyan]")
            try:
                browser, context = platform.get_authenticated_context(p, headless=headless)
                if not browser or not context:
                    console.print(f"[yellow]Session expired for {platform.display_name}. Run login_{platform.name}.bat to authenticate.[/yellow]")
                    continue

                page = context.new_page()
                try:
                    stats = platform.search_jobs(page, settings)
                    console.print(f"[bold green][OK] {platform.display_name} finished: {stats.get('found', 0)} listings found, {stats.get('new', 0)} new jobs added.[/bold green]")
                finally:
                    browser.close()
            except Exception as e:
                logger.error(f"Scraper error on platform {platform.name}: {e}", exc_info=True)
                console.print(f"[bold red][ERROR] Error scraping {platform.display_name}: {e}[/bold red]")
                console.print("[dim]Continuing to next platform...[/dim]")


def cmd_rank(sites: Optional[List[str]] = None):
    """Score unscored jobs in the DB using Groq LLM across all platforms or selected sites."""
    init_db()
    if sites:
        for s in sites:
            console.print(f"[cyan]Starting Groq LLM Fit Scoring for platform '{s}'...[/cyan]")
            stats = run_ranker(platform=s)
            console.print(f"[bold green]Ranking for {s} finished! {stats['processed']} scored, {stats['qualified']} qualified for apply stage.[/bold green]")
    else:
        console.print("[cyan]Starting Groq LLM Fit Scoring across unscored jobs...[/cyan]")
        stats = run_ranker()
        console.print(f"[bold green]Ranking finished! {stats['processed']} scored, {stats['qualified']} qualified for apply stage.[/bold green]")



def cmd_apply(sites: Optional[List[str]] = None, dry_run: Optional[bool] = None):
    """Run application pipeline for qualified jobs across enabled platforms."""
    init_db()
    settings = load_settings()
    if dry_run is not None:
        settings.setdefault("execution", {})["dry_run"] = dry_run

    headless = settings.get("execution", {}).get("headless", False)
    platforms = get_enabled_platforms(settings, requested_sites=sites)
    min_score = settings.get("filters", {}).get("min_relevance_score", 75)
    max_apps = settings.get("filters", {}).get("max_applications_per_run", 20)

    if not platforms:
        console.print("[yellow]No active platforms found for apply stage.[/yellow]")
        return

    from .utils import load_resume
    from .db import get_jobs_for_application
    resume_text = load_resume()

    with sync_playwright() as p:
        for platform in platforms:
            console.print(f"\n[bold cyan]== Applying on {platform.display_name} ==[/bold cyan]")
            
            # Fetch qualified jobs for this specific platform
            eligible_jobs = get_jobs_for_application(min_score=min_score, limit=max_apps, platform=platform.name)
            if not eligible_jobs:
                console.print(f"[dim]No qualified jobs in database for {platform.display_name} (min score: {min_score}).[/dim]")
                continue

            console.print(f"[cyan]Found {len(eligible_jobs)} qualified jobs ready for {platform.display_name}.[/cyan]")

            try:
                browser, context = platform.get_authenticated_context(p, headless=headless)
                if not browser or not context:
                    console.print(f"[yellow]Session expired for {platform.display_name}. Run login_{platform.name}.bat to authenticate.[/yellow]")
                    continue

                page = context.new_page()
                stats = {"applied": 0, "staged": 0, "skipped": 0, "failed": 0, "already_applied": 0, "redirect": 0}

                try:
                    for job in eligible_jobs:
                        result = platform.apply(page, job, settings, resume_text)
                        if result in stats:
                            stats[result] += 1
                        elif result == "already applied":
                            stats["already_applied"] += 1
                        elif result == "external redirect":
                            stats["redirect"] += 1

                    console.print(f"[bold green][OK] Application run for {platform.display_name} finished! Results: {stats}[/bold green]")
                finally:
                    browser.close()
            except Exception as e:
                logger.error(f"Application error on platform {platform.name}: {e}", exc_info=True)
                console.print(f"[bold red][ERROR] Error applying on {platform.display_name}: {e}[/bold red]")
                console.print("[dim]Continuing with next platform...[/dim]")




def cmd_run_all(sites: Optional[List[str]] = None, dry_run: Optional[bool] = None):
    """Execute end-to-end pipeline: Scrape -> Rank -> Apply across enabled platforms."""
    init_db()
    settings = load_settings()
    if dry_run is not None:
        settings.setdefault("execution", {})["dry_run"] = dry_run

    console.print("[bold magenta]Starting Full Multi-Platform Agent Pipeline...[/bold magenta]")
    
    # 1. Scrape
    console.print("\n[bold cyan]Step 1/3: Multi-Platform Scraping[/bold cyan]")
    cmd_scrape(sites=sites)

    # 2. Rank
    console.print("\n[bold cyan]Step 2/3: Unified LLM Relevance Ranking[/bold cyan]")
    cmd_rank(sites=sites)

    # 3. Apply
    console.print("\n[bold cyan]Step 3/3: Multi-Platform Apply Pipeline[/bold cyan]")
    cmd_apply(sites=sites, dry_run=dry_run)

    console.print("\n[bold green]End-to-End Pipeline Complete![/bold green]")
    cmd_summary()


def cmd_summary():
    """Display current database summary statistics."""
    init_db()
    stats = get_summary_stats()
    
    table = Table(title="Multi-Platform Agent Status Summary", header_style="bold cyan")
    table.add_column("Status Lifecycle", style="bold")
    table.add_column("Count", justify="right", style="green")

    for status, count in stats.items():
        if status != "total":
            table.add_row(status.capitalize(), str(count))

    table.add_section()
    table.add_row("Total Jobs Tracked", str(stats.get("total", 0)), style="bold yellow")
    
    console.print(table)


def cmd_health():
    """Quick selector and connectivity health check on platforms."""
    init_db()
    console.print("[cyan]Running Naukri Selector Health Check...[/cyan]")
    
    naukri_platform = get_platform("naukri")
    if not naukri_platform:
        console.print("[red]Naukri platform adapter not found.[/red]")
        return

    with sync_playwright() as p:
        browser, context = naukri_platform.get_authenticated_context(p, headless=False)
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
            SELECT id, title, company, location, platform, relevance_score, applied_at, screenshot_path 
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
    table.add_column("Platform", style="magenta", width=10)
    table.add_column("Job Title", style="bold white")
    table.add_column("Company", style="white")
    table.add_column("Location", style="white")
    table.add_column("Score", justify="center", style="bold green", width=7)
    table.add_column("Applied At", style="dim", width=20)

    for r in rows:
        table.add_row(
            str(r["id"]),
            str(r["platform"] or "Naukri").capitalize(),
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
    parser = argparse.ArgumentParser(description="Multi-Platform Job Search & Apply Agent")
    parser.add_argument(
        "command",
        choices=["init", "login", "scrape", "rank", "apply", "run", "summary", "health", "applied", "export", "schedule"],
        help="Command to execute"
    )
    parser.add_argument(
        "--sites",
        type=str,
        default=None,
        help="Comma-separated list of target sites (e.g., 'naukri,linkedin,indeed')"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=None,
        help="Run without submitting actual applications"
    )

    args = parser.parse_args()
    selected_sites = parse_site_list(args.sites)

    if args.command == "init":
        cmd_init()
    elif args.command == "login":
        cmd_login(sites=selected_sites)
    elif args.command == "scrape":
        cmd_scrape(sites=selected_sites)
    elif args.command == "rank":
        cmd_rank(sites=selected_sites)
    elif args.command == "apply":
        cmd_apply(sites=selected_sites, dry_run=args.dry_run)
    elif args.command == "applied":
        cmd_applied()
    elif args.command == "export":
        cmd_export()
    elif args.command == "schedule":
        cmd_schedule()
    elif args.command == "run":
        cmd_run_all(sites=selected_sites, dry_run=args.dry_run)
    elif args.command == "summary":
        cmd_summary()
    elif args.command == "health":
        cmd_health()


if __name__ == "__main__":
    main()
