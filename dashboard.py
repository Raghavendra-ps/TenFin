#!/usr/bin/env python3

import os
import re
import io
import shutil # Added for potential recursive deletion if needed later
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
# Determine paths relative to *this* script file using pathlib
# This ensures the paths work correctly regardless of where the script is run from,
# as long as the directory structure (scraped_data, templates) is maintained relative to dashboard.py
try:
    SCRIPT_DIR = Path(__file__).parent.resolve()
except NameError:
     # Fallback if __file__ is not defined (e.g., interactive interpreter)
     # This is less reliable for deployed applications.
    SCRIPT_DIR = Path('.').resolve()
    print(f"Warning: __file__ not defined, using current directory as SCRIPT_DIR: {SCRIPT_DIR}")


# --- CORRECTED PATH DEFINITIONS using pathlib ---
# Ensure BASE_PATH is defined as a Path object using SCRIPT_DIR (which is also a Path object)
BASE_PATH = SCRIPT_DIR / "scraped_data"         # Path object for base data
# Now FILTERED_PATH can be correctly defined using the / operator because BASE_PATH is a Path object
FILTERED_PATH = BASE_PATH / "Filtered Tenders"  # Path object for filtered results
TEMPLATES_DIR = SCRIPT_DIR / "templates"        # Path object for Jinja2 templates
FILTERED_TENDERS_FILENAME = "Filtered_Tenders.txt" # Standard filename within subdirs

# --- FastAPI App Setup ---
app = FastAPI(title="TenFin Tender Dashboard")

# --- Template Engine Setup ---
templates: Optional[Jinja2Templates] = None
if not TEMPLATES_DIR.is_dir():
    print(f"ERROR: Templates directory not found at '{TEMPLATES_DIR}'")
    print("       HTML responses will likely fail.")
    # You could raise an exception here to prevent startup:
    # raise RuntimeError(f"Required templates directory not found: {TEMPLATES_DIR}")
else:
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR)) # Jinja2 needs string path


# === HELPER FUNCTIONS ===

# Regex to find lines starting with digits followed by a dot and optional space
TENDER_BLOCK_START_PATTERN = re.compile(r"^\s*\d+\.\s*")
# Example patterns for extracting info (adjust based on *exact* format)
TITLE_PATTERN = re.compile(r"^\s*\[([^\]]+)\]")
TENDER_ID_PATTERN = re.compile(r"\[Tender ID:\s*([^\]]+)\]", re.IGNORECASE)
DEPARTMENT_PATTERN = re.compile(r"(?:Department|Organisation Name):\s*(.*)", re.IGNORECASE) # Match "Department:" or "Organisation Name:"

def _validate_subdir(subdir: str) -> Path:
    """
    Validates subdir name to prevent path traversal and returns the full, resolved Path object.
    Raises HTTPException if the name is invalid or points outside the allowed directory.
    """
    if not subdir or ".." in subdir or subdir.startswith(("/", "\\")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid subdirectory name.")

    # Resolve the path safely within the intended parent
    try:
        # Create the potential path using the FILTERED_PATH object
        full_path = FILTERED_PATH / subdir
        # Resolve it to an absolute path. Use strict=False initially.
        resolved_path = full_path.resolve(strict=False)

        # Security Check: Ensure the resolved path is truly inside FILTERED_PATH's resolved path.
        # This uses the Path objects comparison logic.
        if FILTERED_PATH.resolve(strict=False) not in resolved_path.parents:
             raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Path traversal attempt detected.")

    except Exception as e: # Catch potential OS errors during resolution
        print(f"Error resolving path for subdir '{subdir}': {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error processing path.")

    return resolved_path # Return the resolved Path object

def parse_tenders_from_file(filepath: Path) -> List[Dict[str, str]]:
    """
    Parses tender information from a structured text file.

    Args:
        filepath: Path object pointing to the tender file.

    Returns:
        A list of dictionaries, where each dictionary represents a tender.

    Note: This parser relies heavily on the specific format of the input file.
          See comments within _parse_single_tender_block for format assumptions.
          It will be fragile if the file format changes.
    """
    if not filepath.is_file():
        # This specific error is often handled by the calling endpoint with 404
        raise FileNotFoundError(f"Tender file not found: {filepath}")

    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f: # Added errors='ignore' for flexibility
            lines = f.readlines()
    except Exception as e:
        print(f"ERROR: Could not read file {filepath}: {e}")
        # Re-raise or handle as appropriate for the context
        raise IOError(f"Failed to read file: {filepath}") from e

    tenders: List[Dict[str, str]] = []
    current_block_lines: List[str] = []

    for line in lines:
        line_stripped = line.strip()
        if not line_stripped: # Skip empty lines within or between blocks
            continue

        if TENDER_BLOCK_START_PATTERN.match(line_stripped):
            if current_block_lines: # Process the completed previous block
                tender_data = _parse_single_tender_block(current_block_lines)
                if tender_data:
                    tenders.append(tender_data)
            current_block_lines = [line_stripped] # Start the new block
        elif current_block_lines: # Add line to the current block if it has started
            current_block_lines.append(line_stripped)
        # else: Ignore lines before the first 'N.' marker

    # Process the very last block after the loop finishes
    if current_block_lines:
        tender_data = _parse_single_tender_block(current_block_lines)
        if tender_data:
            tenders.append(tender_data)

    return tenders

def _parse_single_tender_block(block_lines: List[str]) -> Optional[Dict[str, str]]:
    """
    Helper function to parse a single block of tender lines into a dictionary.
    Assumes specific formatting within the block (dates first, bracketed title, etc.).
    """
    if not block_lines:
        return None

    tender: Dict[str, str] = {
        "raw_block_header": block_lines[0], # Keep the original block identifier line (e.g., "1.")
        "start_date": "N/A",
        "end_date": "N/A",
        "opening_date": "N/A",
        "title": "N/A",
        "tender_id": "N/A",
        "department": "N/A",
    }

    # Attempt to parse dates (assuming they are the lines immediately after the block start ID)
    potential_date_lines = block_lines[1:4] # Get lines index 1, 2, 3 if they exist
    tender["start_date"] = potential_date_lines[0] if len(potential_date_lines) > 0 else "N/A"
    tender["end_date"] = potential_date_lines[1] if len(potential_date_lines) > 1 else "N/A"
    tender["opening_date"] = potential_date_lines[2] if len(potential_date_lines) > 2 else "N/A"

    # Attempt to parse other fields using regex or keywords
    title_found = False
    search_lines = block_lines[1:] # Search lines after the header
    for line in search_lines:
        # Prioritize finding specific patterns first
        id_match = TENDER_ID_PATTERN.search(line)
        if id_match and tender["tender_id"] == "N/A": # Only take first match
            tender["tender_id"] = id_match.group(1).strip()
            continue # Found ID

        dept_match = DEPARTMENT_PATTERN.search(line)
        if dept_match and tender["department"] == "N/A": # Only take first match
            tender["department"] = dept_match.group(1).strip()
            continue # Found Dept

        # Try matching title (usually less specific pattern)
        title_match = TITLE_PATTERN.match(line)
        if title_match and not title_found: # Only take the first bracketed line as title
            tender["title"] = title_match.group(1).strip()
            title_found = True
            # Don't continue here, as the title line might contain other info

    # Optional: Fallback logic for title if needed
    # if not title_found and len(search_lines) > 3:
    #     pass # Implement fallback if necessary

    return tender


# === API ENDPOINTS ===

@app.get("/", response_class=HTMLResponse)
async def homepage(request: Request):
    """Displays the main page listing available filtered tender sets (subdirectories)."""
    if not templates:
         raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Template engine not configured.")

    subdirs: List[str] = []
    # Use the FILTERED_PATH Path object here
    if FILTERED_PATH.is_dir():
        try:
            # List only directories within FILTERED_PATH
            subdirs = sorted([
                item.name for item in FILTERED_PATH.iterdir() if item.is_dir()
            ])
        except OSError as e:
            print(f"ERROR: Could not list directories in '{FILTERED_PATH}': {e}")
            # Render page with empty list or show an error
    else:
        print(f"Warning: Filtered data directory not found: '{FILTERED_PATH}'. It may need to be created.")

    return templates.TemplateResponse("index.html", {"request": request, "subdirs": subdirs})


@app.get("/view/{subdir}", response_class=HTMLResponse)
async def view_tenders(request: Request, subdir: str):
    """Displays the parsed tenders from a specific filtered set."""
    if not templates:
         raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Template engine not configured.")

    try:
        # Validate subdir name and get the resolved Path object
        subdir_path = _validate_subdir(subdir)
        # Use the Path object to construct the file path
        file_path = subdir_path / FILTERED_TENDERS_FILENAME

        # Check if the specific file exists within the validated directory
        if not file_path.is_file():
             raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"File '{FILTERED_TENDERS_FILENAME}' not found in '{subdir}'.")

        # Parse the file using the Path object
        tenders = parse_tenders_from_file(file_path)

    except FileNotFoundError: # Catch specific error from parse_tenders_from_file
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Tender data file not found for '{subdir}'.")
    except HTTPException as e:
        # Re-raise validation errors or other HTTP exceptions
        raise e
    except Exception as e:
        print(f"ERROR: Failed to process view for subdir '{subdir}': {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error reading or parsing tender file.")

    return templates.TemplateResponse("view.html", {
        "request": request,
        "subdir": subdir,
        "tenders": tenders
    })


@app.get("/download/{subdir}")
async def download_tender_excel(subdir: str):
    """Downloads the parsed tenders from a set as an Excel (.xlsx) file."""
    try:
        subdir_path = _validate_subdir(subdir)
        # Use the Path object to construct the file path
        file_path = subdir_path / FILTERED_TENDERS_FILENAME

        if not file_path.is_file():
             raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"File '{FILTERED_TENDERS_FILENAME}' not found in '{subdir}'.")

        # Use Path object here
        tenders = parse_tenders_from_file(file_path)

    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Tender data file not found for '{subdir}'.")
    except HTTPException as e:
        raise e # Re-raise validation errors
    except Exception as e:
        print(f"ERROR: Failed to process download for subdir '{subdir}': {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error preparing download file.")

    # --- Create Excel workbook in memory ---
    wb = Workbook()
    ws = wb.active
    ws.title = subdir[:31] # Worksheet title limit

    headers = list(tenders[0].keys()) if tenders else [
        "raw_block_header", "start_date", "end_date", "opening_date",
        "title", "tender_id", "department"
    ]
    ws.append(headers)

    for tender in tenders:
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
    filename = f"{safe_subdir}_{FILTERED_TENDERS_FILENAME.replace('.txt', '.xlsx')}"

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
    # Use the BASE_PATH Path object
    if BASE_PATH.is_dir():
        try:
            # Use Path object's iterdir() method
            tender_files = sorted([
                f.name for f in BASE_PATH.iterdir()
                if f.is_file() and f.name.startswith("Final_Tender_List") and f.name.endswith(".txt")
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
    file: str = Form(...), # Source filename string
    state: str = Form(...),
    start_date: str = Form(...),
    end_date: str = Form(...)
):
    """Processes the filter form submission and runs the filter engine."""
    if not templates:
         raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Template engine not configured.")

    # --- Input Validation ---
    if not filter_name or ".." in filter_name or filter_name.startswith(("/", "\\")) or "/" in filter_name or "\\" in filter_name :
         return templates.TemplateResponse("error.html", {
            "request": request,
            "error": "Invalid Filter Name. It cannot be empty, contain '..', or path separators (/ or \\)."
        }, status_code=status.HTTP_400_BAD_REQUEST)

    # Use the BASE_PATH Path object to check source file
    source_file_path = (BASE_PATH / file).resolve()
    if not source_file_path.is_file() or BASE_PATH.resolve() not in source_file_path.parents:
         return templates.TemplateResponse("error.html", {
            "request": request,
            "error": f"Selected source file '{file}' is invalid or not found in the base data directory."
        }, status_code=status.HTTP_400_BAD_REQUEST)

    # --- Execute Filter ---
    try:
        keyword_list = [kw.strip() for kw in keywords.split(",") if kw.strip()]

        if 'run_filter' not in globals() or not callable(run_filter):
             raise RuntimeError("Filter engine (run_filter function) is not available.")

        # Call the filter engine function - pass BASE_PATH Path object
        result_path_str = run_filter(
            base_folder=BASE_PATH,      # Pass the Path object
            tender_filename=file,       # Pass the filename string relative to base_folder
            keywords=keyword_list,
            use_regex=regex,
            filter_name=filter_name,
            state=state,
            start_date=start_date,
            end_date=end_date
        )

        expected_subdir = f"{filter_name} Tenders"

        if not result_path_str or not Path(result_path_str).is_file():
             print(f"Warning: run_filter returned an unexpected path: {result_path_str}")

        return templates.TemplateResponse("success.html", {
            "request": request,
            "subdir": expected_subdir,
            "result_path": str(result_path_str)
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


# Use POST for destructive actions like deletion
@app.post("/delete/{subdir}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tender_set(subdir: str):
    """Deletes a filtered tender set directory and its contents."""
    try:
        folder_to_delete = _validate_subdir(subdir) # Returns a resolved Path object

        if not folder_to_delete.is_dir():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Directory '{subdir}' not found.")

        print(f"Attempting to delete directory: {folder_to_delete}")
        shutil.rmtree(folder_to_delete)
        print(f"Successfully deleted directory: {folder_to_delete}")

    except HTTPException as e:
        raise e # Re-raise validation errors or 404
    except OSError as e:
        print(f"ERROR: Could not delete directory '{folder_to_delete}': {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to delete directory: {e.strerror}")
    except Exception as e:
        print(f"ERROR: Unexpected error during deletion of '{subdir}': {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An unexpected server error occurred during deletion.")

    # Redirect back to homepage using GET after successful POST action
    return RedirectResponse(url=app.url_path_for("homepage"), status_code=status.HTTP_303_SEE_OTHER)


# Optional: Add endpoint to serve static files if needed
# from fastapi.staticfiles import StaticFiles
# STATIC_DIR = SCRIPT_DIR / "static"
# if STATIC_DIR.is_dir():
#    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Optional: Development server run block (for use with `python dashboard.py`)
# if __name__ == "__main__":
#     import uvicorn
#     print(f"--- Starting Uvicorn Development Server ---")
#     print(f"Base data path: {BASE_PATH}")
#     print(f"Filtered data path: {FILTERED_PATH}")
#     print(f"Templates path: {TEMPLATES_DIR}")
#     if not templates:
#          print("WARNING: Templates directory missing or not configured!")
#     print(f"Access at: http://127.0.0.1:8000")
#     print("--- (Press CTRL+C to stop) ---")
#     uvicorn.run("dashboard:app", host="127.0.0.1", port=8000, reload=True)
