# --- START OF FILE TenFin-main/dashboard.py ---

#!/usr/bin/env python3

import os
import re
import io
import shutil
import json # Import the json library
from pathlib import Path
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, Request, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from openpyxl import Workbook

# --- Attempt to import custom module with error handling ---
try:
    # Assuming filter_engine.py is in the same directory or Python path
    from filter_engine import run_filter, INDIAN_STATES
except ImportError:
    print("ERROR: Could not import 'filter_engine'. Ensure 'filter_engine.py' exists.")
    print("       Dashboard functionality related to running filters will be unavailable.")
    # Define placeholders so the app can still potentially run
    INDIAN_STATES = ["Error: State List Unavailable"]
    def run_filter(*args, **kwargs):
        """Placeholder function when filter_engine is missing."""
        raise RuntimeError("filter_engine module is not available. Cannot run filter.")

# === CONFIGURATION ===
try:
    SCRIPT_DIR = Path(__file__).parent.resolve()
except NameError:
    SCRIPT_DIR = Path('.').resolve()
    print(f"Warning: __file__ not defined, using current directory as SCRIPT_DIR: {SCRIPT_DIR}")

# --- Path Definitions using pathlib ---
BASE_PATH = SCRIPT_DIR / "scraped_data"
FILTERED_PATH = BASE_PATH / "Filtered Tenders"
TEMPLATES_DIR = SCRIPT_DIR / "templates"
# --- UPDATED: Expect JSON file from filter engine ---
FILTERED_TENDERS_FILENAME = "Filtered_Tenders.json"

# --- FastAPI App Setup ---
app = FastAPI(title="TenFin Tender Dashboard")

# --- Template Engine Setup ---
templates: Optional[Jinja2Templates] = None
if not TEMPLATES_DIR.is_dir():
    print(f"ERROR: Templates directory not found at '{TEMPLATES_DIR}'")
    print("       HTML responses will likely fail.")
else:
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# === HELPER FUNCTIONS ===

def _validate_subdir(subdir: str) -> Path:
    """
    Validates subdir name to prevent path traversal and returns the full, resolved Path object.
    Raises HTTPException if the name is invalid or points outside the allowed directory.
    """
    if not subdir or ".." in subdir or subdir.startswith(("/", "\\")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid subdirectory name.")

    try:
        full_path = FILTERED_PATH / subdir
        resolved_path = full_path.resolve(strict=False)
        if FILTERED_PATH.resolve(strict=False) not in resolved_path.parents:
             raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Path traversal attempt detected.")
    except Exception as e:
        print(f"Error resolving path for subdir '{subdir}': {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error processing path.")

    return resolved_path

# --- REMOVED PARSING FUNCTIONS ---
# def parse_tenders_from_file(filepath: Path) -> List[Dict[str, str]]:
#     ... (Removed) ...
# def _parse_single_tender_block(block_lines: List[str]) -> Optional[Dict[str, str]]:
#     ... (Removed) ...
# --- END OF REMOVAL ---


# === API ENDPOINTS ===

@app.get("/", response_class=HTMLResponse)
async def homepage(request: Request):
    """Displays the main page listing available filtered tender sets (subdirectories)."""
    if not templates:
         raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Template engine not configured.")

    subdirs: List[str] = []
    if FILTERED_PATH.is_dir():
        try:
            subdirs = sorted([item.name for item in FILTERED_PATH.iterdir() if item.is_dir()])
        except OSError as e:
            print(f"ERROR: Could not list directories in '{FILTERED_PATH}': {e}")
    else:
        print(f"Warning: Filtered data directory not found: '{FILTERED_PATH}'. It may need to be created.")

    return templates.TemplateResponse("index.html", {"request": request, "subdirs": subdirs})


@app.get("/view/{subdir}", response_class=HTMLResponse)
async def view_tenders(request: Request, subdir: str):
    """Displays the parsed tenders from a specific filtered set by reading JSON."""
    if not templates:
         raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Template engine not configured.")

    tenders: List[Dict[str, Any]] = [] # Initialize as empty list
    try:
        subdir_path = _validate_subdir(subdir)
        # --- MODIFIED: Point to the JSON file ---
        file_path = subdir_path / FILTERED_TENDERS_FILENAME

        if not file_path.is_file():
             raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"File '{FILTERED_TENDERS_FILENAME}' not found in '{subdir}'.")

        # --- MODIFIED: Read and parse JSON ---
        print(f"Reading tender data from: {file_path}")
        with open(file_path, "r", encoding="utf-8") as f:
            tenders = json.load(f) # Directly load the list of dictionaries
        # Basic validation if needed: ensure it's a list
        if not isinstance(tenders, list):
             print(f"ERROR: JSON data in {file_path} is not a list.")
             raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Invalid tender data format.")

    except FileNotFoundError: # Should be caught by the is_file() check above, but good practice
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Tender data file not found for '{subdir}'.")
    except json.JSONDecodeError:
        print(f"ERROR: Invalid JSON content in {file_path}")
        # Log the error for debugging, but show generic error to user
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error reading tender data file format.")
    except HTTPException as e:
        # Re-raise validation errors or other HTTP exceptions
        raise e
    except Exception as e:
        print(f"ERROR: Failed to process view for subdir '{subdir}': {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error loading or processing tender data.")

    # Pass the loaded list of dictionaries directly to the template
    return templates.TemplateResponse("view.html", {
        "request": request,
        "subdir": subdir,
        "tenders": tenders # Pass the list of dicts loaded from JSON
    })


@app.get("/download/{subdir}")
async def download_tender_excel(subdir: str):
    """Downloads the parsed tenders from a set as an Excel (.xlsx) file by reading JSON."""
    tenders: List[Dict[str, Any]] = []
    try:
        subdir_path = _validate_subdir(subdir)
        # --- MODIFIED: Point to the JSON file ---
        file_path = subdir_path / FILTERED_TENDERS_FILENAME

        if not file_path.is_file():
             raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"File '{FILTERED_TENDERS_FILENAME}' not found in '{subdir}'.")

        # --- MODIFIED: Read and parse JSON ---
        print(f"Reading tender data for download from: {file_path}")
        with open(file_path, "r", encoding="utf-8") as f:
            tenders = json.load(f) # Directly load the list of dictionaries
        if not isinstance(tenders, list):
             print(f"ERROR: JSON data in {file_path} is not a list.")
             raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Invalid tender data format.")

    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Tender data file not found for '{subdir}'.")
    except json.JSONDecodeError:
        print(f"ERROR: Invalid JSON content in {file_path}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error reading tender data file format.")
    except HTTPException as e:
        raise e # Re-raise validation errors
    except Exception as e:
        print(f"ERROR: Failed to process download for subdir '{subdir}': {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error preparing download file.")

    # --- Create Excel workbook in memory (Logic remains similar) ---
    wb = Workbook()
    ws = wb.active
    ws.title = subdir[:31] # Worksheet title limit

    # Define headers based on keys of the first tender dict (if available)
    # It's crucial that filter_engine saves consistent keys for all dicts
    if tenders:
        # Define desired order or get from first item
        headers = list(tenders[0].keys())
        # You might want a specific order:
        # headers = ["start_date", "end_date", "opening_date", "tender_id", "title", "department", "state", ...] # Define desired order
        ws.append(headers)
    else:
        # Define default headers if no tenders exist in the JSON
        ws.append(["start_date", "end_date", "opening_date", "tender_id", "title", "department", "state", "raw_block_header"])

    # Add data rows using dict.get() for safety
    for tender in tenders:
        # Ensure row has values for all expected headers, in the correct order
        ws.append([tender.get(header, "N/A") for header in headers])

    # --- Save to a BytesIO buffer ---
    excel_buffer = io.BytesIO()
    try:
        wb.save(excel_buffer)
        excel_buffer.seek(0) # Reset buffer position
    except Exception as e:
         print(f"ERROR: Failed saving workbook to buffer: {e}")
         raise HTTPException(status_code=500, detail="Failed to generate Excel file content.")

    # --- Create filename ---
    safe_subdir = re.sub(r'[^\w\-]+', '_', subdir)
    # --- MODIFIED: Change downloaded filename extension ---
    filename = f"{safe_subdir}_{FILTERED_TENDERS_FILENAME.replace('.json', '.xlsx')}"

    # --- Return StreamingResponse ---
    return StreamingResponse(
        excel_buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=\"{filename}\""}
    )


@app.get("/run-filter", response_class=HTMLResponse)
async def run_filter_form(request: Request):
    """Displays the form to run a new filter operation."""
    if not templates:
         raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Template engine not configured.")

    tender_files: List[str] = []
    if BASE_PATH.is_dir():
        try:
            tender_files = sorted([
                f.name for f in BASE_PATH.iterdir()
                if f.is_file() and f.name.startswith("Final_Tender_List") and f.name.endswith(".txt") # Still lists source .txt files
            ])
        except OSError as e:
             print(f"ERROR: Could not list tender source files in '{BASE_PATH}': {e}")
    else:
        print(f"Warning: Base data directory not found: '{BASE_PATH}'")

    current_states = INDIAN_STATES if 'INDIAN_STATES' in globals() else ["Error: State List Unavailable"]

    return templates.TemplateResponse("run_filter.html", {
        "request": request,
        "tender_files": tender_files,
        "states": current_states
    })


@app.post("/run-filter", response_class=HTMLResponse)
async def run_filter_submit(
    request: Request,
    keywords: str = Form(""),
    regex: bool = Form(False),
    filter_name: str = Form(...),
    file: str = Form(...), # Source filename string (.txt)
    state: str = Form(...),
    start_date: str = Form(...),
    end_date: str = Form(...)
):
    """Processes the filter form submission and calls the filter engine."""
    if not templates:
         raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Template engine not configured.")

    if not filter_name or ".." in filter_name or filter_name.startswith(("/", "\\")) or "/" in filter_name or "\\" in filter_name :
         return templates.TemplateResponse("error.html", {
            "request": request,
            "error": "Invalid Filter Name. It cannot be empty, contain '..', or path separators (/ or \\)."
        }, status_code=status.HTTP_400_BAD_REQUEST)

    source_file_path = (BASE_PATH / file).resolve()
    if not source_file_path.is_file() or BASE_PATH.resolve() not in source_file_path.parents:
         return templates.TemplateResponse("error.html", {
            "request": request,
            "error": f"Selected source file '{file}' is invalid or not found in the base data directory."
        }, status_code=status.HTTP_400_BAD_REQUEST)

    try:
        keyword_list = [kw.strip() for kw in keywords.split(",") if kw.strip()]
        if 'run_filter' not in globals() or not callable(run_filter):
             raise RuntimeError("Filter engine (run_filter function) is not available.")

        # Call the filter engine - it should now return the path to the .json file
        result_path_str = run_filter(
            base_folder=BASE_PATH,
            tender_filename=file,
            keywords=keyword_list,
            use_regex=regex,
            filter_name=filter_name,
            state=state,
            start_date=start_date,
            end_date=end_date
        )
        expected_subdir = f"{filter_name} Tenders"

        # Optional check if the result path seems valid (is a .json file now)
        if not result_path_str or not Path(result_path_str).is_file() or not result_path_str.endswith(".json"):
             print(f"Warning: run_filter returned an unexpected or non-JSON path: {result_path_str}")

        return templates.TemplateResponse("success.html", {
            "request": request,
            "subdir": expected_subdir,
            "result_path": str(result_path_str) # Display the path to the created JSON file
        })

    except FileNotFoundError as e:
         print(f"ERROR: File not found during filter run: {e}")
         return templates.TemplateResponse("error.html", {"request": request, "error": f"File operation error: {e}"}, status_code=404)
    except ValueError as e:
         print(f"ERROR: Value error during filter run: {e}")
         return templates.TemplateResponse("error.html", {"request": request, "error": str(e)}, status_code=400)
    except RuntimeError as e:
         print(f"ERROR: Runtime error during filter run: {e}")
         return templates.TemplateResponse("error.html", {"request": request, "error": str(e)}, status_code=503)
    except Exception as e:
        print(f"ERROR: Unexpected error running filter engine for '{filter_name}': {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": f"An unexpected server error occurred while running the filter: {type(e).__name__}"
        }, status_code=500)


@app.post("/delete/{subdir}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tender_set(subdir: str):
    """Deletes a filtered tender set directory and its contents."""
    try:
        folder_to_delete = _validate_subdir(subdir)
        if not folder_to_delete.is_dir():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Directory '{subdir}' not found.")

        print(f"Attempting to delete directory: {folder_to_delete}")
        shutil.rmtree(folder_to_delete)
        print(f"Successfully deleted directory: {folder_to_delete}")

    except HTTPException as e:
        raise e
    except OSError as e:
        print(f"ERROR: Could not delete directory '{folder_to_delete}': {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to delete directory: {e.strerror}")
    except Exception as e:
        print(f"ERROR: Unexpected error during deletion of '{subdir}': {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An unexpected server error occurred during deletion.")

    return RedirectResponse(url=app.url_path_for("homepage"), status_code=status.HTTP_303_SEE_OTHER)

# --- END OF FILE TenFin-main/dashboard.py ---
