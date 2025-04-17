# --- START OF FILE TenFin-main/filter_engine.py ---

import re
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any

# --- Constants ---
# (Keep constants as before)
TENDER_BLOCK_PATTERN = re.compile(r"^\d+\.\s*$")
INDIAN_STATES = [ "Andhra Pradesh", "Arunachal Pradesh", # ... (full list) ...
]
TWO_BRACKET_ID_REGEX = re.compile(r"^\s*\[[^\]]+\]\s*\[(\d{4}_\w+_\d+_\d+)\]\s*$")
TAG_REGEX = {
    "Date": re.compile(r"<[Dd][Aa][Tt][Ee]>\s*(.*?)\s*</[Dd][Aa][Tt][Ee]>", re.DOTALL),
    "Title": re.compile(r"<[Tt][Ii][Tt][Ll][Ee]>\s*(.*?)\s*</[Tt][Ii][Tt][Ll][Ee]>", re.DOTALL),
    "ID": re.compile(r"<[Ii][Dd]>\s*(.*?)\s*</[Ii][Dd]>", re.DOTALL),
    "Department": re.compile(r"<[Dd][Ee][Pp][Aa][Rr][Tt][Mm][Ee][Nn][Tt]>\s*(.*?)\s*</[Dd][Ee][Pp][Aa][Rr][Tt][Mm][Ee][Nn][Tt]>", re.DOTALL),
    "Link": re.compile(r"<[Ll][Ii][Nn][Kk]>\s*(.*?)\s*</[Ll][Ii][Nn][Kk]>", re.DOTALL),
}
ORG_KEYWORDS = ["Authority", "Limited", "Department", "..."] # Add full list back

def parse_tender_blocks_from_tagged_file(file_path: Path) -> List[str]:
    # (Keep implementation as before)
    if not file_path.is_file(): print(f"[FE] ERROR: File not found {file_path}"); return []
    try: content = file_path.read_text(encoding="utf-8", errors='ignore')
    except Exception as e: print(f"[FE] ERROR: Read failed {file_path}: {e}"); return []
    raw_blocks = [b for b in content.split("--- TENDER START ---") if b.strip()]
    processed_blocks = [re.sub(r"--- TENDER END ---.*", "", b, flags=re.DOTALL).strip() for b in raw_blocks]
    print(f"[FE] DEBUG: Split {len(processed_blocks)} blocks from {file_path.name}")
    return [b for b in processed_blocks if b]

def extract_tender_info_from_tagged_block(block_text: str) -> Dict[str, Any]:
     # (Keep implementation as before)
    tender: Dict[str, Any] = {"start_date": "N/A", "end_date": "N/A", "opening_date": "N/A", "title": "N/A", "tender_id": "N/A", "department": "N/A", "state": "N/A", "link": "N/A"}
    try: dates = TAG_REGEX["Date"].findall(block_text); tender["start_date"] = dates[0].strip(); tender["end_date"] = dates[1].strip(); tender["opening_date"] = dates[2].strip()
    except IndexError: pass
    except Exception as e: print(f"[FE] ERROR extracting Dates: {e}")
    try: title_match = TAG_REGEX["Title"].search(block_text); tender["title"] = title_match.group(1).strip() if title_match else "N/A"
    except Exception as e: print(f"[FE] ERROR extracting Title: {e}")
    try: id_match = TAG_REGEX["ID"].search(block_text); tender["tender_id"] = id_match.group(1).strip() if id_match else "N/A"
    except Exception as e: print(f"[FE] ERROR extracting ID: {e}")
    try: dept_match = TAG_REGEX["Department"].search(block_text); tender["department"] = dept_match.group(1).strip() if dept_match else "N/A"
    except Exception as e: print(f"[FE] ERROR extracting Department: {e}")
    try: link_match = TAG_REGEX["Link"].search(block_text); tender["link"] = link_match.group(1).strip() if link_match else "N/A"
    except Exception as e: print(f"[FE] ERROR extracting Link: {e}")
    if tender["department"] != "N/A":
        try:
            for state_name in INDIAN_STATES:
                if re.search(r'\b' + re.escape(state_name) + r'\b', tender["department"], re.IGNORECASE): tender["state"] = state_name; break
        except Exception as e: print(f"[FE] ERROR extracting State: {e}")
    return tender


# --- CORRECTED matches_filters function ---
def matches_filters(tender: Dict[str, Any], keywords: List[str], use_regex: bool, state_filter: Optional[str], start_date_str: Optional[str], end_date_str: Optional[str]) -> bool:
    """
    Checks if a parsed tender dictionary matches the filter criteria.
    Applies BOTH start and end date filters against the E-PUBLISH DATE.
    Uses DD-Mon-YYYY format for parsing tender dates.
    """
    # State Filter
    if state_filter and state_filter.lower() not in tender.get("state", "N/A").lower():
        return False

    # Date Filtering
    tender_date_format = "%d-%b-%Y" # Format like 04-Apr-2025
    filter_date_format = "%Y-%m-%d" # Format from HTML form date input

    tender_publish_date = None
    tender_publish_date_str = tender.get("start_date", "") # ePublish date
    if tender_publish_date_str and tender_publish_date_str != "N/A":
        try:
            # Try parsing only the date part first, assuming format might vary
            date_part_str = tender_publish_date_str.split(" ")[0]
            tender_publish_date = datetime.strptime(date_part_str, tender_date_format).date()
        except ValueError:
            print(f"[Filter Engine] WARNING: Could not parse ePublish Date '{tender_publish_date_str}' with format '{tender_date_format}'. Skipping date filters.")
            tender_publish_date = None

    # Apply Start Date Filter
    if start_date_str and tender_publish_date:
        try: # Needs its own try block
            filter_start_date = datetime.strptime(start_date_str, filter_date_format).date()
            if tender_publish_date < filter_start_date:
                return False
        # --- ADDED THIS BLOCK BACK ---
        except ValueError:
             print(f"[Filter Engine] WARNING: Could not parse filter Start Date '{start_date_str}'")
             pass # Ignore this specific filter check if user input is bad
        # --- END ADDED BLOCK ---

    # Apply End Date Filter
    if end_date_str and tender_publish_date:
        try: # Needs its own try block
            filter_end_date = datetime.strptime(end_date_str, filter_date_format).date()
            if tender_publish_date > filter_end_date:
                return False
        except ValueError:
             print(f"[Filter Engine] WARNING: Could not parse filter End Date '{end_date_str}'")
             pass # Ignore this specific filter check if user input is bad

    # Keyword Filter
    # (No changes needed here)
    search_content = " ".join(str(tender.get(k, "")) for k in ["title", "tender_id", "department", "state", "link"])
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
    print("--- Running Filter (Engine v3.4: Corrected Date Filter Syntax) ---")
    print(f"  Source File: {tender_filename}")
    # ... (rest of print statements) ...
    print("-----------------------------------------------------------------")

    tender_path = base_folder / tender_filename
    tagged_blocks = parse_tender_blocks_from_tagged_file(tender_path)
    if not tagged_blocks: print("[FE] WARNING: No blocks parsed.")

    matching_tender_dictionaries: List[Dict[str, Any]] = []
    processed_count = 0; match_count = 0
    for block_text in tagged_blocks:
        processed_count += 1
        tender_info = extract_tender_info_from_tagged_block(block_text)
        if matches_filters(tender_info, keywords, use_regex, state, start_date, end_date):
            matching_tender_dictionaries.append(tender_info)
            match_count += 1

    print(f"[FE] Processed {processed_count} blocks, found {match_count} matching.")
    output_folder = base_folder / "Filtered Tenders" / f"{filter_name} Tenders"
    output_folder.mkdir(parents=True, exist_ok=True)
    output_filename = "Filtered_Tenders.json"
    output_path = output_folder / output_filename
    try:
        print(f"[FE] Saving {match_count} dicts to: {output_path}")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(matching_tender_dictionaries, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[FE] ERROR: Failed write {output_path}: {e}")
        raise IOError(f"Failed write output JSON: {e}") from e
    return str(output_path.resolve())

# --- END OF FILE TenFin-main/filter_engine.py ---
