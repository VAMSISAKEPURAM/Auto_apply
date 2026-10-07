import time
import schedule
from datetime import datetime
from rich.console import Console
from rich.panel import Panel

from .utils import load_settings, setup_logger
from .db import init_db, get_summary_stats
from .exporter import export_jobs_to_excel

logger = setup_logger("scheduler")
console = Console()


def run_hourly_job_cycle():
    """
    Execute one full automated multi-platform cycle:
    1. Scrape latest listings across all configured platforms (Naukri, LinkedIn, Foundit, Indeed, Shine, Instahyre)
    2. Score & rank against resume with Groq LLM
    3. Apply to qualified jobs across enabled platforms (hands-free)
    4. Export updated Excel report
    """
    init_db()
    settings = load_settings()
    dry_run = settings.get("execution", {}).get("dry_run", False)
    
    cycle_start = datetime.now()
    console.print(Panel(
        f"[bold cyan]Starting Automated Multi-Platform Cycle[/bold cyan]\n"
        f"[white]Timestamp: {cycle_start.strftime('%Y-%m-%d %H:%M:%S')}[/white]\n"
        f"[white]Configured Platforms: {settings.get('sites', ['naukri'])}[/white]",
        border_style="cyan"
    ))

    try:
        from .main import cmd_scrape, cmd_rank, cmd_apply

        # 1. Scrape across enabled platforms
        console.print("\n[bold cyan]Phase 1/4: Scraping Latest Job Postings Across Platforms...[/bold cyan]")
        cmd_scrape()

        # 2. Rank with Groq LLM
        console.print("\n[bold cyan]Phase 2/4: Groq LLM Fit Scoring & Filtering...[/bold cyan]")
        cmd_rank()

        # 3. Apply to Qualified Jobs across enabled platforms
        console.print("\n[bold cyan]Phase 3/4: Applying to Qualified Jobs...[/bold cyan]")
        cmd_apply(dry_run=dry_run)

        # 4. Generate & Save Excel Report
        console.print("\n[bold cyan]Phase 4/4: Exporting Excel Report...[/bold cyan]")
        excel_path = export_jobs_to_excel()

        summary = get_summary_stats()
        console.print(Panel(
            f"[bold green]Hourly Multi-Platform Cycle Completed Successfully![/bold green]\n\n"
            f"• Excel Report: [underline green]{excel_path}[/underline green]\n"
            f"• Total Tracked in DB: {summary.get('total', 0)}",
            title="Cycle Summary",
            border_style="green"
        ))

    except Exception as e:
        logger.error(f"Error occurred during hourly automated cycle: {e}", exc_info=True)
        console.print(f"[bold red]Cycle encountered an error: {e}. Will retry in next hourly schedule.[/bold red]")


def start_scheduler_daemon(interval_hours: int = 1):
    """
    Run continuous scheduler daemon firing every N hours across all enabled platforms.
    """
    settings = load_settings()
    sites = settings.get("sites", ["naukri", "linkedin", "foundit", "indeed", "shine", "instahyre"])
    
    console.print(Panel.fit(
        f"[bold green]Multi-Platform 24/7 Automated Job Apply Daemon[/bold green]\n"
        f"[white]• Active Platforms: {', '.join(sites)}[/white]\n"
        f"[white]• Interval: Every {interval_hours} Hour(s)[/white]\n"
        f"[white]• Real-time Excel Export: reports/applied_jobs_latest.xlsx[/white]",
        border_style="green"
    ))

    # Run immediate first cycle on launch
    console.print("\n[yellow]Executing initial multi-platform job cycle now...[/yellow]")
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

