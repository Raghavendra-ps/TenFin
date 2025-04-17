# --- START OF FILE TenFin-main/filter_engine.py ---

import re
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any

# --- Constants ---
INDIAN_STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh",
    "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka",
    "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya",
    "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim",
    "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand",
    "West Bengal", "Delhi", "Jammu and Kashmir", "Ladakh", "Puducherry",
    "Chandigarh", "Andaman and Nicobar Islands", "Dadra and Nagar Haveli and Daman and Diu", "Lakshadweep"
]

# --- Regex for Tag Extraction (Case-insensitive tag names, non-greedy content) ---
# This version makes the tag names case-insensitive ([Tt]itle) and ensures robustness
TAG_REGEX = {
    "Date": re.compile(r"<[Dd][Aa][Tt][Ee]>\s*(.*?)\s*</[Dd][Aa][Tt][Ee]>", re.DOTALL),
    "Title": re.compile(r"<[Tt][Ii][Tt][Ll][Ee]>\s*(.*?)\s*</[Tt][Ii][Tt][Ll][Ee]>", re.DOTALL),
    "ID": re.compile(r"<[Ii][Dd]>\s*(.*?)\s*</[Ii][Dd]>", re.DOTALL),
    "Department": re.compile(r"<[Dd][Ee][Pp][Aa][Rr][Tt][Mm][Ee][Nn][Tt]>\s*(.*?)\s*</[Dd][Ee][Pp][Aa][Rr][Tt][Mm][Ee][Nn][Tt]>", re.DOTALL),
}

def parse_tender_blocks_from_tagged_file(file_path: Path) -> List[str]:
    """Reads the file and splits it into tagged tender blocks using delimiters."""
    if not file_path.is_file():
        print(f"[Filter Engine] ERROR: Tender source file not found at {file_path}")
        return []
    try:
        # Read the whole content at once
        content = file_path.read_text(encoding="utf-8", errors='ignore')
    except Exception as e:
        print(f"[Filter Engine] ERROR: Failed to read file {file_path}: {e}")
        return []

    # Split based on the start delimiter, filter out potential empty strings from start/end
    raw_blocks = [block for block in content.split("--- TENDER START ---") if block.strip()]

    processed_blocks: List[str] = []
    for raw_block in raw_blocks:
        # Remove the end delimiter and surrounding whitespace robustly
        block_content = re.sub(r"--- TENDER END ---.*", "", raw_block, flags=re.DOTALL).strip()
        if block_content:
            processed_blocks.append(block_content)

    print(f"[Filter Engine] DEBUG: Split into {len(processed_blocks)} tagged blocks from {file_path.name}")
    return processed_blocks


def extract_tender_info_from_tagged_block(block_text: str) -> Dict[str, Any]:
    """
    Extracts structured info from a pre-tagged block of text using revised regex.
    Maps extracted data to keys expected by the dashboard template. Includes Debugging.
    """
    print("\n[Filter Engine] --- EXTRACTING FROM BLOCK ---") # DEBUG
    print(f"Block Length: {len(block_text)}") # DEBUG
    print(block_text[:500] + "..." if len(block_text) > 500 else block_text) # Print start of block
    print("[Filter Engine] -----------------------------") # DEBUG

    tender: Dict[str, Any] = {
        "start_date": "N/A", "end_date": "N/A", "opening_date": "N/A",
        "title": "N/A", "tender_id": "N/A", "department": "N/A", "state": "N/A",
    }

    # Extract Dates using findall
    try:
        dates = TAG_REGEX["Date"].findall(block_text)
        print(f"[Filter Engine] DEBUG Found Dates: {dates}") # DEBUG
        if len(dates) > 0: tender["start_date"] = dates[0].strip()
        if len(dates) > 1: tender["end_date"] = dates[1].strip()
        if len(dates) > 2: tender["opening_date"] = dates[2].strip()
    except Exception as e:
        print(f"[Filter Engine] ERROR extracting Dates: {e}")

    # Extract Title, ID, Department using search
    try:
        title_match = TAG_REGEX["Title"].search(block_text)
        print(f"[Filter Engine] DEBUG Title Match: {title_match}") # DEBUG
        if title_match: tender["title"] = title_match.group(1).strip()
    except Exception as e:
         print(f"[Filter Engine] ERROR extracting Title: {e}")

    try:
        id_match = TAG_REGEX["ID"].search(block_text)
        print(f"[Filter Engine] DEBUG ID Match: {id_match}") # DEBUG
        if id_match: tender["tender_id"] = id_match.group(1).strip()
    except Exception as e:
         print(f"[Filter Engine] ERROR extracting ID: {e}")

    try:
        dept_match = TAG_REGEX["Department"].search(block_text)
        print(f"[Filter Engine] DEBUG Department Match: {dept_match}") # DEBUG
        if dept_match: tender["department"] = dept_match.group(1).strip()
    except Exception as e:
        print(f"[Filter Engine] ERROR extracting Department: {e}")


    # Extract State from Department text
    if tender["department"] != "N/A":
        try:
            for state_name in INDIAN_STATES:
                # Using word boundary \b to avoid partial matches within words
                if re.search(r'\b' + re.escape(state_name) + r'\b', tender["department"], re.IGNORECASE):
                    tender["state"] = state_name
                    break
        except Exception as e:
             print(f"[Filter Engine] ERROR extracting State: {e}")


    print(f"[Filter Engine] DEBUG Resulting Tender Dict: {tender}") # DEBUG
    return tender


def matches_filters(tender: Dict[str, Any], keywords: List[str], use_regex: bool, state_filter: Optional[str], start_date_str: Optional[str], end_date_str: Optional[str]) -> bool:
    """Checks if a parsed tender dictionary matches the filter criteria."""
    # (No changes needed here)
    # State Filter
    if state_filter and state_filter.lower() not in tender.get("state", "N/A").lower():
        return False
    # Date Filtering
    tender_datetime_format = "%d-%b-%Y %I:%M %p"
    filter_date_format = "%Y-%m-%d"
    if start_date_str:
        try:
            filter_start_date = datetime.strptime(start_date_str, filter_date_format).date()
            tender_start_str = tender.get("start_date", "")
            if tender_start_str and tender_start_str != "N/A":
                tender_start_dt = datetime.strptime(tender_start_str, tender_datetime_format)
                if tender_start_dt.date() < filter_start_date: return False
        except ValueError: pass
    if end_date_str:
        try:
            filter_end_date = datetime.strptime(end_date_str, filter_date_format).date()
            tender_end_str = tender.get("end_date", "")
            if tender_end_str and tender_end_str != "N/A":
                tender_end_dt = datetime.strptime(tender_end_str, tender_datetime_format)
                if tender_end_dt.date() < filter_end_date: return False
        except ValueError: pass
    # Keyword Filter
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
    return True


def run_filter(base_folder: Path, tender_filename: str, keywords: list, use_regex: bool, filter_name: str, state: str, start_date: str, end_date: str) -> str:
    """Runs the filtering process using tagged input file and saves results as JSON."""
    # (No changes needed here)
    print("--- Running Filter (Engine v3.2: Debug Tag Extraction) ---")
    print(f"  Source File: {tender_filename}")
    # ... (rest of print statements) ...
    print("-----------------------------------------------------------")

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
