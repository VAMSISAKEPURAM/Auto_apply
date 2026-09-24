import os
from datetime import datetime
from pathlib import Path
from typing import Optional
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from .utils import PROJECT_ROOT, setup_logger
from .db import get_db_connection, get_summary_stats

logger = setup_logger("exporter")
REPORTS_DIR = PROJECT_ROOT / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def export_jobs_to_excel(output_filename: Optional[str] = None) -> Path:
    """
    Export all applied and tracked jobs into a beautifully formatted Excel (.xlsx) workbook.
    Saves to reports/applied_jobs_latest.xlsx and a timestamped copy.
    """
    wb = openpyxl.Workbook()
    # Remove default sheet
    wb.remove(wb.active)

    # Styles
    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    
    score_high_fill = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")
    score_med_fill = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
    
    thin_border = Border(
        left=Side(style='thin', color='D9D9D9'),
        right=Side(style='thin', color='D9D9D9'),
        top=Side(style='thin', color='D9D9D9'),
        bottom=Side(style='thin', color='D9D9D9')
    )

    with get_db_connection() as conn:
        cursor = conn.cursor()

        # ==========================================
        # SHEET 1: Applied Jobs
        # ==========================================
        ws_applied = wb.create_sheet(title="Applied Jobs")
        applied_headers = [
            "Job ID", "Job Title", "Company", "Location", "Experience", 
            "Fit Score", "Fit Justification", "Applied Timestamp", "Job URL", "Screening Q&A"
        ]
        ws_applied.append(applied_headers)

        cursor.execute("""
            SELECT id, title, company, location, experience, relevance_score, 
                   justification, applied_at, url, screening_qa 
            FROM jobs 
            WHERE status = 'applied' 
            ORDER BY applied_at DESC, id DESC
        """)
        applied_rows = cursor.fetchall()

        for row in applied_rows:
            ws_applied.append([
                row["id"],
                row["title"],
                row["company"],
                row["location"],
                row["experience"],
                row["relevance_score"],
                row["justification"],
                str(row["applied_at"] or ""),
                row["url"],
                row["screening_qa"] or ""
            ])

        # Format Sheet 1
        for col_idx, _ in enumerate(applied_headers, 1):
            cell = ws_applied.cell(row=1, column=col_idx)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center" if col_idx in [1, 6, 8] else "left", vertical="center")

        for row_idx in range(2, len(applied_rows) + 2):
            for col_idx in range(1, len(applied_headers) + 1):
                cell = ws_applied.cell(row=row_idx, column=col_idx)
                cell.border = thin_border
                cell.alignment = Alignment(vertical="center")
                # Highlight score
                if col_idx == 6:
                    score = cell.value or 0
                    if score >= 80:
                        cell.fill = score_high_fill
                    elif score >= 70:
                        cell.fill = score_med_fill
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                # Hyperlink for URL
                if col_idx == 9 and cell.value:
                    cell.font = Font(color="0563C1", underline="single")

        # ==========================================
        # SHEET 2: All Tracked Jobs
        # ==========================================
        ws_all = wb.create_sheet(title="All Tracked Jobs")
        all_headers = [
            "Job ID", "Status", "Job Title", "Company", "Location", 
            "Experience", "Fit Score", "Justification", "Posted Date", "Job URL"
        ]
        ws_all.append(all_headers)

        cursor.execute("""
            SELECT id, status, title, company, location, experience, 
                   relevance_score, justification, posted_date, url 
            FROM jobs 
            ORDER BY relevance_score DESC, id DESC
        """)
        all_rows = cursor.fetchall()

        for row in all_rows:
            ws_all.append([
                row["id"],
                row["status"].capitalize(),
                row["title"],
                row["company"],
                row["location"],
                row["experience"],
                row["relevance_score"],
                row["justification"],
                row["posted_date"],
                row["url"]
            ])

        # Format Sheet 2
        for col_idx, _ in enumerate(all_headers, 1):
            cell = ws_all.cell(row=1, column=col_idx)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center" if col_idx in [1, 2, 7] else "left", vertical="center")

        for row_idx in range(2, len(all_rows) + 2):
            for col_idx in range(1, len(all_headers) + 1):
                cell = ws_all.cell(row=row_idx, column=col_idx)
                cell.border = thin_border
                cell.alignment = Alignment(vertical="center")
                if col_idx == 7:
                    score = cell.value or 0
                    if score >= 80:
                        cell.fill = score_high_fill
                    elif score >= 70:
                        cell.fill = score_med_fill
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                if col_idx == 10 and cell.value:
                    cell.font = Font(color="0563C1", underline="single")

        # ==========================================
        # Auto-fit Column Widths
        # ==========================================
        for ws in [ws_applied, ws_all]:
            for col in ws.columns:
                max_len = 0
                col_letter = get_column_letter(col[0].column)
                for cell in col:
                    val_str = str(cell.value or "")
                    if len(val_str) > max_len:
                        max_len = len(val_str)
                # Bound width reasonably
                ws.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 45)

    # Save files
    latest_path = REPORTS_DIR / "applied_jobs_latest.xlsx"
    wb.save(str(latest_path))

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    timestamped_path = REPORTS_DIR / f"applied_jobs_{timestamp}.xlsx"
    wb.save(str(timestamped_path))

    logger.info(f"Excel report successfully generated at {latest_path}")
    return latest_path
