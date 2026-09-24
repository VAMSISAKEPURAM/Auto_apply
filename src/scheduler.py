import time
import schedule
from datetime import datetime, timedelta
from rich.console import Console
from rich.panel import Panel
from playwright.sync_api import sync_playwright

from .utils import load_settings, setup_logger
from .db import init_db, get_summary_stats
from .auth import ensure_authenticated_context
from .scraper import run_scraper
from .ranker import run_ranker
from .applier import run_applier
from .exporter import export_jobs_to_excel

logger = setup_logger("scheduler")
console = Console()


def run_hourly_job_cycle():
    """
    Execute one full automated cycle:
    1. Scrape latest listings
    2. Score & rank against resume with Groq LLM
    3. Apply to top 20 qualified jobs (non-interactive, hands-free)
    4. Export updated Excel report
    """
    init_db()
    settings = load_settings()
    headless = settings.get("execution", {}).get("headless", False)
    
    cycle_start = datetime.now()
    console.print(Panel(
        f"[bold cyan]Starting Automated Hourly Cycle[/bold cyan]\n"
        f"[white]Timestamp: {cycle_start.strftime('%Y-%m-%d %H:%M:%S')}[/white]",
        border_style="cyan"
    ))

    try:
        with sync_playwright() as p:
            browser, context = ensure_authenticated_context(p, headless=headless)
            page = context.new_page()
            try:
                # 1. Scrape
                console.print("\n[bold cyan]Phase 1/4: Scraping Latest Job Postings...[/bold cyan]")
                scrape_stats = run_scraper(page, settings)

                # 2. Rank with Groq LLM
                console.print("\n[bold cyan]Phase 2/4: Groq LLM Fit Scoring & Filtering...[/bold cyan]")
                rank_stats = run_ranker(limit=50)

                # 3. Apply to Top 20 Qualified Jobs
                console.print("\n[bold cyan]Phase 3/4: Applying to Top Qualified Jobs...[/bold cyan]")
                apply_stats = run_applier(page)

                # 4. Generate & Save Excel Report
                console.print("\n[bold cyan]Phase 4/4: Exporting Excel Report...[/bold cyan]")
                excel_path = export_jobs_to_excel()

                summary = get_summary_stats()
                console.print(Panel(
                    f"[bold green]Hourly Cycle Completed Successfully![/bold green]\n\n"
                    f"• Scraped: {scrape_stats.get('new', 0)} new jobs\n"
                    f"• Scored: {rank_stats.get('processed', 0)} jobs ({rank_stats.get('qualified', 0)} qualified)\n"
                    f"• Applied: {apply_stats.get('applied', 0)} jobs\n"
                    f"• Excel Report: [underline green]{excel_path}[/underline green]\n"
                    f"• Total Tracked in DB: {summary.get('total', 0)}",
                    title="Cycle Summary",
                    border_style="green"
                ))

            finally:
                browser.close()

    except Exception as e:
        logger.error(f"Error occurred during hourly automated cycle: {e}", exc_info=True)
        console.print(f"[bold red]Cycle encountered an error: {e}. Will retry in next hourly schedule.[/bold red]")


def start_scheduler_daemon(interval_hours: int = 1):
    """
    Run continuous scheduler daemon firing every N hours.
    """
    console.print(Panel.fit(
        f"[bold green]Naukri 24/7 Automated Job Apply Daemon[/bold green]\n"
        f"[white]• Interval: Every {interval_hours} Hour(s)[/white]\n"
        f"[white]• Max Applications/Hour: 20[/white]\n"
        f"[white]• Real-time Excel Export: reports/applied_jobs_latest.xlsx[/white]",
        border_style="green"
    ))

    # Run immediate first cycle on launch
    console.print("\n[yellow]Executing initial job cycle now...[/yellow]")
    run_hourly_job_cycle()

    # Schedule recurring runs
    schedule.every(interval_hours).hours.do(run_hourly_job_cycle)

    console.print(f"\n[cyan]Scheduler is running. Next cycle will trigger in {interval_hours} hour(s). Press Ctrl+C to stop.[/cyan]\n")

    while True:
        try:
            schedule.run_pending()
            time.sleep(30)
        except KeyboardInterrupt:
            console.print("\n[yellow]Scheduler stopped by user.[/yellow]")
            break
        except Exception as e:
            logger.error(f"Scheduler loop exception: {e}")
            time.sleep(60)
