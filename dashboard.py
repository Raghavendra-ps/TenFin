# --- START OF FILE TenFin-main/dashboard.py ---

#!/usr/bin/env python3

import os
import re
import io
import shutil
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
import datetime # Ensure datetime is imported

from fastapi import FastAPI, Request, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from openpyxl import Workbook

# --- Attempt to import custom module ---
try:
    from filter_engine import run_filter, INDIAN_STATES
except ImportError:
    print("ERROR: Could not import 'filter_engine'.")
    INDIAN_STATES = ["Error: State List Unavailable"]
    def run_filter(*args, **kwargs): raise RuntimeError("filter_engine not available.")

# === CONFIGURATION ===
try:
    SCRIPT_DIR = Path(__file__).parent.resolve()
except NameError:
    SCRIPT_DIR = Path('.').resolve()
BASE_PATH = SCRIPT_DIR / "scraped_data"
FILTERED_PATH = BASE_PATH / "Filtered Tenders"
TEMPLATES_DIR = SCRIPT_DIR / "templates"
FILTERED_TENDERS_FILENAME = "Filtered_Tenders.json"

# --- FastAPI App Setup ---
app = FastAPI(title="TenFin Tender Dashboard")

# --- Template Engine Setup ---
templates: Optional[Jinja2Templates] = None
if not TEMPLATES_DIR.is_dir(): print(f"ERROR: Templates directory not found: '{TEMPLATES_DIR}'")
else: templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# === HELPER FUNCTIONS ===
def _validate_subdir(subdir: str) -> Path:
    # (Keep existing function)
    if not subdir or ".." in subdir or subdir.startswith(("/", "\\")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid subdirectory name.")
    try:
        full_path = FILTERED_PATH / subdir
        resolved_path = full_path.resolve(strict=False)
        if resolved_path.parent != FILTERED_PATH.resolve(strict=False):
             raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Path traversal attempt detected.")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error processing path.")
    return resolved_path

# === API ENDPOINTS ===

@app.get("/", response_class=HTMLResponse)
async def homepage(request: Request):
    # (Keep existing function)
    if not templates: raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Template engine not configured.")
    subdirs: List[str] = []
    if FILTERED_PATH.is_dir():
        try: subdirs = sorted([item.name for item in FILTERED_PATH.iterdir() if item.is_dir()])
        except OSError as e: print(f"ERROR: Could not list directories in '{FILTERED_PATH}': {e}")
    else: print(f"Warning: Filtered data directory not found: '{FILTERED_PATH}'.")
    return templates.TemplateResponse("index.html", {"request": request, "subdirs": subdirs})

@app.get("/view/{subdir}", response_class=HTMLResponse)
async def view_tenders(request: Request, subdir: str):
    # (Keep existing function - already passes full dict)
    if not templates: raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Template engine not configured.")
    tenders: List[Dict[str, Any]] = []
    try:
        subdir_path = _validate_subdir(subdir)
        file_path = subdir_path / FILTERED_TENDERS_FILENAME
        if not file_path.is_file(): raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"File '{FILTERED_TENDERS_FILENAME}' not found.")
        with open(file_path, "r", encoding="utf-8") as f: tenders = json.load(f)
        if not isinstance(tenders, list): raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Invalid tender data format.")
    except Exception as e: raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error loading tender data: {e}")
    return templates.TemplateResponse("view.html", {"request": request, "subdir": subdir, "tenders": tenders})

@app.get("/download/{subdir}")
async def download_tender_excel(subdir: str):
    """Downloads a single tender set as an Excel (.xlsx) file."""
    tenders: List[Dict[str, Any]] = []
    try:
        subdir_path = _validate_subdir(subdir)
        file_path = subdir_path / FILTERED_TENDERS_FILENAME
        if not file_path.is_file(): raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"File '{FILTERED_TENDERS_FILENAME}' not found.")
        with open(file_path, "r", encoding="utf-8") as f: tenders = json.load(f)
        if not isinstance(tenders, list): raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Invalid tender data format.")
    except Exception as e: raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error preparing download: {e}")

    wb = Workbook(); ws = wb.active; ws.title = subdir[:31]
    # --- UPDATED default headers ---
    headers = ["start_date", "end_date", "opening_date", "tender_id", "title", "department", "state", "link"]
    if tenders and isinstance(tenders[0], dict): headers = list(tenders[0].keys()) # Dynamic headers override default if data exists
    ws.append(headers)
    for tender in tenders: ws.append([tender.get(header, "N/A") for header in headers])

    excel_buffer = io.BytesIO(); wb.save(excel_buffer); excel_buffer.seek(0)
    safe_subdir = re.sub(r'[^\w\-]+', '_', subdir)
    filename = f"{safe_subdir}_{FILTERED_TENDERS_FILENAME.replace('.json', '.xlsx')}"
    return StreamingResponse(excel_buffer, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f"attachment; filename=\"{filename}\""})

@app.get("/run-filter", response_class=HTMLResponse)
async def run_filter_form(request: Request):
    # (Keep existing function)
    if not templates: raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Template engine not configured.")
    current_states = INDIAN_STATES if 'INDIAN_STATES' in globals() else ["Error: State List Unavailable"]
    return templates.TemplateResponse("run_filter.html", {"request": request, "states": current_states})

@app.post("/run-filter", response_class=HTMLResponse)
async def run_filter_submit(request: Request, keywords: str = Form(""), regex: bool = Form(False), filter_name: str = Form(...), state: str = Form(...), start_date: str = Form(...), end_date: str = Form(...)):
    # (Keep existing function)
    if not templates: raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Template engine not configured.")
    if not filter_name or ".." in filter_name or filter_name.startswith(("/", "\\")) or "/" in filter_name or "\\" in filter_name :
         return templates.TemplateResponse("error.html", {"request": request, "error": "Invalid Filter Name."}, status_code=status.HTTP_400_BAD_REQUEST)
    latest_tender_filename = None
    try:
        source_files = sorted([p for p in BASE_PATH.glob("Final_Tender_List_*.txt") if p.is_file()], key=lambda p: p.name, reverse=True)
        if not source_files: return templates.TemplateResponse("error.html", {"request": request, "error": "No source tender list files found."}, status_code=status.HTTP_404_NOT_FOUND)
        latest_tender_filename = source_files[0].name; print(f"Using latest source file: {latest_tender_filename}")
    except OSError as e: return templates.TemplateResponse("error.html", {"request": request, "error": "Error accessing source tender data."}, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    try:
        keyword_list = [kw.strip() for kw in keywords.split(",") if kw.strip()]
        if 'run_filter' not in globals() or not callable(run_filter): raise RuntimeError("Filter engine not available.")
        result_path_str = run_filter( base_folder=BASE_PATH, tender_filename=latest_tender_filename, keywords=keyword_list, use_regex=regex, filter_name=filter_name, state=state, start_date=start_date, end_date=end_date )
        expected_subdir = f"{filter_name} Tenders"
        if not result_path_str or not Path(result_path_str).is_file() or not result_path_str.endswith(".json"): print(f"Warning: run_filter returned unexpected path: {result_path_str}")
        return templates.TemplateResponse("success.html", {"request": request, "subdir": expected_subdir, "result_path": str(result_path_str)})
    except Exception as e: print(f"ERROR running filter: {type(e).__name__}: {e}"); import traceback; traceback.print_exc(); return templates.TemplateResponse("error.html", {"request": request, "error": f"Error running filter: {type(e).__name__}"}, status_code=500)

@app.get("/regex-help", response_class=HTMLResponse)
async def regex_help_page(request: Request):
    # (Keep existing function)
    if not templates: raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Template engine not configured.")
    return templates.TemplateResponse("regex_help.html", {"request": request})

@app.post("/delete/{subdir}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tender_set(subdir: str):
    # (Keep existing function)
    try: folder_to_delete = _validate_subdir(subdir); shutil.rmtree(folder_to_delete)
    except Exception as e: raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Delete failed: {e}")
    return RedirectResponse(url=app.url_path_for("homepage"), status_code=status.HTTP_303_SEE_OTHER)

@app.post("/bulk-delete", status_code=status.HTTP_204_NO_CONTENT)
async def bulk_delete_tender_sets(selected_subdirs: List[str] = Form(...)):
    # (Keep existing function)
    if not selected_subdirs: return RedirectResponse(url=app.url_path_for("homepage"), status_code=status.HTTP_303_SEE_OTHER)
    for subdir in selected_subdirs:
        try: folder_to_delete = _validate_subdir(subdir); shutil.rmtree(folder_to_delete)
        except Exception as e: print(f"Error deleting {subdir}: {e}") # Log errors but continue
    return RedirectResponse(url=app.url_path_for("homepage"), status_code=status.HTTP_303_SEE_OTHER)

# --- UPDATED: /bulk-download Endpoint ---
@app.post("/bulk-download")
async def bulk_download_tender_excel(selected_subdirs: List[str] = Form(...)):
    """Creates a single Excel file with multiple sheets for selected tender sets."""
    if not selected_subdirs: raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No sets selected.")
    wb = Workbook(); wb.remove(wb.active); processed_sheets = 0; errors = []
    # --- UPDATED headers ---
    headers = ["start_date", "end_date", "opening_date", "tender_id", "title", "department", "state", "link"]

    for subdir in selected_subdirs:
        tenders: List[Dict[str, Any]] = []
        try:
            subdir_path = _validate_subdir(subdir)
            file_path = subdir_path / FILTERED_TENDERS_FILENAME
            if not file_path.is_file(): errors.append(f"Data missing for '{subdir}'."); continue
            with open(file_path, "r", encoding="utf-8") as f: tenders = json.load(f)
            if not isinstance(tenders, list): errors.append(f"Invalid data for '{subdir}'."); continue

            safe_sheet_title = re.sub(r'[\\/*?:\[\]]+', '_', subdir)[:31]; ws = wb.create_sheet(title=safe_sheet_title)
            current_headers = headers # Use default header order
            if tenders and isinstance(tenders[0], dict):
                 # Optionally use dynamic headers if keys vary significantly, but keep order consistent if possible
                 # current_headers = list(tenders[0].keys())
                 # Ensure 'link' is included if dynamically generated headers might miss it
                 if "link" not in current_headers: current_headers.append("link")
            ws.append(current_headers)
            for tender in tenders: ws.append([tender.get(header, "N/A") for header in current_headers])
            processed_sheets += 1; print(f"Added sheet for '{subdir}' to bulk download.")
        except Exception as e: errors.append(f"Error processing '{subdir}'.")

    if processed_sheets == 0: raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Could not generate download. Errors: {'; '.join(errors)}")
    excel_buffer = io.BytesIO(); wb.save(excel_buffer); excel_buffer.seek(0)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"Bulk_Tender_Download_{timestamp}.xlsx"
    return StreamingResponse(excel_buffer, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f"attachment; filename=\"{filename}\""})

# --- END OF FILE TenFin-main/dashboard.py ---
