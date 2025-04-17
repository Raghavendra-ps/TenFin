# --- START OF FILE TenFin-main/filter_engine.py ---

import re
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any

# --- Constants ---
TENDER_BLOCK_PATTERN = re.compile(r"^\d+\.\s*$")
INDIAN_STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh",
    "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka",
    "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya",
    "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim",
    "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand",
    "West Bengal", "Delhi", "Jammu and Kashmir", "Ladakh", "Puducherry",
    "Chandigarh", "Andaman and Nicobar Islands", "Dadra and Nagar Haveli and Daman and Diu", "Lakshadweep"
]
# Regex for the specific two-bracket ID format
TWO_BRACKET_ID_REGEX = re.compile(r"^\s*\[[^\]]+\]\s*\[(\d{4}_\w+_\d+_\d+)\]\s*$")
# Regex for Tag Extraction
TAG_REGEX = {
    "Date": re.compile(r"<Date>\s*(.*?)\s*</Date>", re.DOTALL),
    "Title": re.compile(r"<Title>\s*(.*?)\s*</Title>", re.DOTALL),
    "ID": re.compile(r"<ID>\s*(.*?)\s*</ID>", re.DOTALL),
    "Department": re.compile(r"<Department>\s*(.*?)\s*</Department>", re.DOTALL),
}
# Organisation Keywords (Shortened for brevity, full list assumed from previous context)
ORG_KEYWORDS = ["Authority", "Limited", "Department", "Institute", "University", "Nigam", "..."] # Add full list back

def parse_tender_blocks_from_tagged_file(file_path: Path) -> List[str]:
    """Reads the file and splits it into tagged tender blocks using delimiters."""
    # (No changes needed in this function)
    if not file_path.is_file():
        print(f"[Filter Engine] ERROR: Tender source file not found at {file_path}")
        return []
    try:
        content = file_path.read_text(encoding="utf-8", errors='ignore')
    except Exception as e:
        print(f"[Filter Engine] ERROR: Failed to read file {file_path}: {e}")
        return []
    raw_blocks = [block for block in content.split("--- TENDER START ---") if block.strip()]
    processed_blocks: List[str] = []
    for raw_block in raw_blocks:
        block_content = re.sub(r"--- TENDER END ---.*", "", raw_block, flags=re.DOTALL).strip()
        if block_content: processed_blocks.append(block_content)
    print(f"[Filter Engine] DEBUG: Split into {len(processed_blocks)} tagged blocks from {file_path.name}")
    return processed_blocks


def extract_tender_info_from_tagged_block(block_text: str) -> Dict[str, Any]:
    """
    Extracts structured info from a pre-tagged block of text using regex.
    Maps extracted data to keys expected by the dashboard template.
    """
    # (No changes needed in this function)
    tender: Dict[str, Any] = {
        "start_date": "N/A", "end_date": "N/A", "opening_date": "N/A",
        "title": "N/A", "tender_id": "N/A", "department": "N/A", "state": "N/A",
    }
    dates = TAG_REGEX["Date"].findall(block_text)
    if len(dates) > 0: tender["start_date"] = dates[0].strip()
    if len(dates) > 1: tender["end_date"] = dates[1].strip()
    if len(dates) > 2: tender["opening_date"] = dates[2].strip()
    title_match = TAG_REGEX["Title"].search(block_text)
    if title_match: tender["title"] = title_match.group(1).strip()
    id_match = TAG_REGEX["ID"].search(block_text)
    if id_match: tender["tender_id"] = id_match.group(1).strip()
    dept_match = TAG_REGEX["Department"].search(block_text)
    if dept_match: tender["department"] = dept_match.group(1).strip()
    if tender["department"] != "N/A":
        for state_name in INDIAN_STATES:
            if re.search(r'\b' + re.escape(state_name) + r'\b', tender["department"], re.IGNORECASE):
                tender["state"] = state_name
                break
    return tender


def matches_filters(tender: Dict[str, Any], keywords: List[str], use_regex: bool, state_filter: Optional[str], start_date_str: Optional[str], end_date_str: Optional[str]) -> bool:
    """
    Checks if a parsed tender dictionary matches the filter criteria.
    Applies BOTH start and end date filters against the E-PUBLISH DATE.
    Uses DD-Mon-YYYY format for parsing tender dates.
    """
    # State Filter
    if state_filter and state_filter.lower() not in tender.get("state", "N/A").lower():
        return False

    # --- Date Filtering (Using Confirmed DD-Mon-YYYY format) ---
    # --- CORRECTED tender_date_format ---
    tender_date_format = "%d-%b-%Y" # Format like 04-Apr-2025
    filter_date_format = "%Y-%m-%d" # Format from HTML form date input

    # Get the tender's publish date string
    tender_publish_date_str = tender.get("start_date", "") # ePublish date
    tender_publish_date = None

    # Try parsing the tender's publish date
    if tender_publish_date_str and tender_publish_date_str != "N/A":
        try:
            tender_publish_date = datetime.strptime(tender_publish_date_str, tender_date_format).date()
        except ValueError:
            print(f"[Filter Engine] WARNING: Could not parse ePublish Date '{tender_publish_date_str}' with format '{tender_date_format}'. Skipping date filters for this tender.")
            # If parsing fails, we cannot apply date filters reliably for this tender
            # Set to None to skip checks below
            tender_publish_date = None

    # Apply Start Date Filter (only if filter date provided AND tender date parsed)
    if start_date_str and tender_publish_date:
        try:
            filter_start_date = datetime.strptime(start_date_str, filter_date_format).date()
            if tender_publish_date < filter_start_date:
                return False # Tender published BEFORE the filter start date
        except ValueError:
             print(f"[Filter Engine] WARNING: Could not parse filter Start Date '{start_date_str}'")
             pass # Ignore this specific filter if user input is bad

    # Apply End Date Filter (only if filter date provided AND tender date parsed)
    if end_date_str and tender_publish_date:
        try:
            filter_end_date = datetime.strptime(end_date_str, filter_date_format).date()
            # Exclude if tender publish date is AFTER filter end date
            if tender_publish_date > filter_end_date:
                return False # Tender published AFTER the filter end date
        except ValueError:
             print(f"[Filter Engine] WARNING: Could not parse filter End Date '{end_date_str}'")
             pass # Ignore this specific filter if user input is bad

    # Keyword Filter
    # (No changes needed here)
    search_content = " ".join(str(tender.get(k, "")) for k in ["title", "tender_id", "department", "state"])
    if keywords:
        if not search_content: return False
        try:
            if use_regex:
                if not any(re.search(kw, search_content, re.IGNORECASE) for kw in keywords): return False
            else:
                content_lower = search_content.lower()
                if not any(kw.lower() in content_lower for kw in keywords): return False
        except re.error as e:
            print(f"[Filter Engine] ERROR: Invalid regex: {e}")
            return False

    # If all checks passed
    return True


def run_filter(base_folder: Path, tender_filename: str, keywords: list, use_regex: bool, filter_name: str, state: str, start_date: str, end_date: str) -> str:
    """Runs the filtering process using tagged input file and saves results as JSON."""
    # (No changes needed here)
    print("--- Running Filter (Engine v3.3: Tagged Input, DD-Mon-YYYY Date Parse) ---")
    print(f"  Source File: {tender_filename}")
    # ... (rest of print statements) ...
    print("--------------------------------------------------------------------------")

    tender_path = base_folder / tender_filename
    tagged_blocks = parse_tender_blocks_from_tagged_file(tender_path)
    if not tagged_blocks: print("[Filter Engine] WARNING: No tender blocks parsed from the source file.")

    matching_tender_dictionaries: List[Dict[str, Any]] = []
    processed_count = 0
    match_count = 0
    for block_text in tagged_blocks:
        processed_count += 1
        tender_info = extract_tender_info_from_tagged_block(block_text)
        if matches_filters(tender_info, keywords, use_regex, state, start_date, end_date):
            matching_tender_dictionaries.append(tender_info)
            match_count += 1

    print(f"[Filter Engine] Processed {processed_count} tagged blocks, found {match_count} matching tenders.")
    output_folder = base_folder / "Filtered Tenders" / f"{filter_name} Tenders"
    output_folder.mkdir(parents=True, exist_ok=True)
    output_filename = "Filtered_Tenders.json"
    output_path = output_folder / output_filename
    try:
        print(f"[Filter Engine] Saving {match_count} matched tender dictionaries to: {output_path}")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(matching_tender_dictionaries, f, indent=2, ensure_ascii=False)
    except TypeError as e:
        print(f"[Filter Engine] ERROR: Failed to serialize tender data to JSON for {output_path}: {e}")
        raise IOError(f"Failed to serialize data to JSON: {e}") from e
    except Exception as e:
        print(f"[Filter Engine] ERROR: Failed to write filtered output JSON file {output_path}: {e}")
        raise IOError(f"Failed to write output JSON file: {e}") from e
    return str(output_path.resolve())

# --- END OF FILE TenFin-main/filter_engine.py ---
