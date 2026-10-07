import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from .utils import PROJECT_ROOT, setup_logger
from .db import get_db_connection

logger = setup_logger("exporter")
REPORTS_DIR = PROJECT_ROOT / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
LATEST_REPORT_PATH = REPORTS_DIR / "applied_jobs_latest.xlsx"

# Standardized column headers for Phase 3
EXCEL_HEADERS = [
    "Date",
    "Site",
    "Company",
    "Job Title",
    "Location",
    "Job URL",
    "Status",
    "Reason"
]

# Standard allowed status values
STATUS_APPLIED = "Applied"
STATUS_ALREADY_APPLIED = "Already Applied"
STATUS_EXTERNAL_REDIRECT = "External Redirect"
STATUS_SKIPPED_QUESTION = "Skipped (Unknown Question)"
STATUS_FAILED = "Failed"

VALID_STATUSES = {
    "applied": STATUS_APPLIED,
    "already applied": STATUS_ALREADY_APPLIED,
    "already_applied": STATUS_ALREADY_APPLIED,
    "external redirect": STATUS_EXTERNAL_REDIRECT,
    "external_redirect": STATUS_EXTERNAL_REDIRECT,
    "skipped (unknown question)": STATUS_SKIPPED_QUESTION,
    "skipped_question": STATUS_SKIPPED_QUESTION,
    "failed": STATUS_FAILED,
    "manual_needed": STATUS_EXTERNAL_REDIRECT,
    "staged": "Staged (Dry-Run)",
    "scraped": "Scraped",
    "scored": "Scored"
}


def normalize_status(raw_status: str, default: str = STATUS_FAILED) -> str:
    """Normalize raw db or code status to standardized Phase 3 status value."""
    if not raw_status:
        return default
    return VALID_STATUSES.get(raw_status.strip().lower(), raw_status)


def get_excel_styles():
    """Return reusable openpyxl styles."""
    return {
        "header_fill": PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid"),
        "header_font": Font(name="Calibri", size=11, bold=True, color="FFFFFF"),
        "status_applied_fill": PatternFill(start_color="D9EAD3", end_color="D9EAD3", fill_type="solid"),  # soft green
        "status_already_fill": PatternFill(start_color="D0E0E3", end_color="D0E0E3", fill_type="solid"),  # soft blue-grey
        "status_redirect_fill": PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid"), # soft yellow
        "status_skipped_fill": PatternFill(start_color="FCE5CD", end_color="FCE5CD", fill_type="solid"),  # soft orange
        "status_failed_fill": PatternFill(start_color="F4CCCC", end_color="F4CCCC", fill_type="solid"),   # soft red
        "thin_border": Border(
            left=Side(style='thin', color='D9D9D9'),
            right=Side(style='thin', color='D9D9D9'),
            top=Side(style='thin', color='D9D9D9'),
            bottom=Side(style='thin', color='D9D9D9')
        ),
        "url_font": Font(color="0563C1", underline="single")
    }


def init_or_load_workbook(file_path: Path = LATEST_REPORT_PATH) -> tuple[openpyxl.Workbook, openpyxl.worksheet.worksheet.Worksheet]:
    """
    Open existing workbook or create a new one with standardized Phase 3 columns.
    Ensures existing rows have Site = 'Naukri' if missing.
    """
    styles = get_excel_styles()

    if file_path.exists():
        try:
            wb = openpyxl.load_workbook(str(file_path))
            ws = wb["Applications"] if "Applications" in wb.sheetnames else wb.active
            # Migrate header if old structure
            existing_headers = [cell.value for cell in ws[1] if cell.value is not None]
            if existing_headers != EXCEL_HEADERS:
                # If old headers, re-export from DB cleanly to prevent column misalignment
                logger.info("Migrating Excel sheet to Phase 3 standardized columns...")
                return build_full_workbook_from_db(file_path)
            return wb, ws
        except Exception as e:
            logger.warning(f"Notice loading existing workbook ({e}), rebuilding fresh workbook...")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Applications"
    ws.append(EXCEL_HEADERS)

    # Format header row
    for col_idx in range(1, len(EXCEL_HEADERS) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = styles["header_fill"]
        cell.font = styles["header_font"]
        cell.alignment = Alignment(horizontal="center" if col_idx in [1, 2, 7] else "left", vertical="center")

    return wb, ws


def build_full_workbook_from_db(file_path: Path = LATEST_REPORT_PATH) -> tuple[openpyxl.Workbook, openpyxl.worksheet.worksheet.Worksheet]:
    """Rebuild full workbook from SQLite DB with Phase 3 schema and migration."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Applications"
    ws.append(EXCEL_HEADERS)

    styles = get_excel_styles()
    for col_idx in range(1, len(EXCEL_HEADERS) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = styles["header_fill"]
        cell.font = styles["header_font"]
        cell.alignment = Alignment(horizontal="center" if col_idx in [1, 2, 7] else "left", vertical="center")

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, platform, title, company, location, url, status, error_message, 
                   justification, applied_at, created_at 
            FROM jobs 
            ORDER BY applied_at DESC, id DESC
        """)
        rows = cursor.fetchall()

        for r in rows:
            site = (r["platform"] or "Naukri").capitalize()
            raw_status = r["status"] or "scraped"
            norm_status = normalize_status(raw_status)
            date_str = str(r["applied_at"] or r["created_at"] or datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            reason = r["error_message"] or r["justification"] or ""

            ws.append([
                date_str,
                site,
                r["company"] or "",
                r["title"] or "",
                r["location"] or "",
                r["url"] or "",
                norm_status,
                reason
            ])

    format_worksheet(ws)
    wb.save(str(file_path))
    return wb, ws


def format_worksheet(ws: openpyxl.worksheet.worksheet.Worksheet):
    """Apply styling, borders, status color-fills, and auto-fit widths."""
    styles = get_excel_styles()
    
    for row_idx in range(2, ws.max_row + 1):
        status_cell = ws.cell(row=row_idx, column=7)
        status_val = str(status_cell.value or "")

        # Set fill based on standardized status
        if status_val == STATUS_APPLIED:
            status_cell.fill = styles["status_applied_fill"]
        elif status_val == STATUS_ALREADY_APPLIED:
            status_cell.fill = styles["status_already_fill"]
        elif status_val == STATUS_EXTERNAL_REDIRECT:
            status_cell.fill = styles["status_redirect_fill"]
        elif status_val == STATUS_SKIPPED_QUESTION:
            status_cell.fill = styles["status_skipped_fill"]
        elif status_val == STATUS_FAILED:
            status_cell.fill = styles["status_failed_fill"]

        for col_idx in range(1, len(EXCEL_HEADERS) + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.border = styles["thin_border"]
            cell.alignment = Alignment(
                horizontal="center" if col_idx in [1, 2, 7] else "left", 
                vertical="center"
            )
            # URL column hyperlink styling
            if col_idx == 6 and cell.value:
                cell.font = styles["url_font"]

    # Auto-fit column widths
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            val_str = str(cell.value or "")
            if len(val_str) > max_len:
                max_len = len(val_str)
        ws.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 50)


def record_application_in_excel(
    job_data: Dict[str, Any], 
    status: str, 
    reason: str = "",
    file_path: Path = LATEST_REPORT_PATH
) -> Path:
    """
    Write or update job row in Excel immediately after application (Atomic per-application write).
    Ensures deduplication on Site + Job URL.
    """
    wb, ws = init_or_load_workbook(file_path)
    
    site = (job_data.get("platform") or "Naukri").capitalize()
    job_url = job_data.get("url", "").strip()
    norm_status = normalize_status(status)
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Check for existing row to dedupe on (Site, Job URL)
    target_row_idx = None
    for row_idx in range(2, ws.max_row + 1):
        cell_site = str(ws.cell(row=row_idx, column=2).value or "").strip().lower()
        cell_url = str(ws.cell(row=row_idx, column=6).value or "").strip()
        if cell_site == site.lower() and cell_url == job_url:
            target_row_idx = row_idx
            break

    row_data = [
        date_str,
        site,
        job_data.get("company", ""),
        job_data.get("title", ""),
        job_data.get("location", ""),
        job_url,
        norm_status,
        reason
    ]

    if target_row_idx:
        # Update existing row
        for col_idx, val in enumerate(row_data, 1):
            ws.cell(row=target_row_idx, column=col_idx, value=val)
    else:
        # Append new row
        ws.append(row_data)

    format_worksheet(ws)
    
    # Save immediately so crashes lose nothing
    wb.save(str(file_path))
    logger.info(f"Excel record updated for job: {job_data.get('title')} [{norm_status}]")
    return file_path


def export_jobs_to_excel(output_filename: Optional[str] = None) -> Path:
    """Export all jobs to latest Excel report and timestamped copy."""
    target_path = REPORTS_DIR / (output_filename or "applied_jobs_latest.xlsx")
    wb, ws = build_full_workbook_from_db(target_path)

    # Save timestamped backup
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    timestamped_path = REPORTS_DIR / f"applied_jobs_{timestamp}.xlsx"
    wb.save(str(timestamped_path))

    logger.info(f"Excel report successfully generated at {target_path}")
    return target_path
