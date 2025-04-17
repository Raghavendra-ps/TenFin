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

# --- Regex for Tag Extraction (Case-insensitive tag names, non-greedy content) ---
TAG_REGEX = {
    "Date": re.compile(r"<[Dd][Aa][Tt][Ee]>\s*(.*?)\s*</[Dd][Aa][Tt][Ee]>", re.DOTALL),
    "Title": re.compile(r"<[Tt][Ii][Tt][Ll][Ee]>\s*(.*?)\s*</[Tt][Ii][Tt][Ll][Ee]>", re.DOTALL),
    "ID": re.compile(r"<[Ii][Dd]>\s*(.*?)\s*</[Ii][Dd]>", re.DOTALL),
    "Department": re.compile(r"<[Dd][Ee][Pp][Aa][Rr][Tt][Mm][Ee][Nn][Tt]>\s*(.*?)\s*</[Dd][Ee][Pp][Aa][Rr][Tt][Mm][Ee][Nn][Tt]>", re.DOTALL),
    "Link": re.compile(r"<[Ll][Ii][Nn][Kk]>\s*(.*?)\s*</[Ll][Ii][Nn][Kk]>", re.DOTALL), # Added Link Regex
}

ORG_KEYWORDS = ["Authority", "Limited", "Department", "Institute", "University", "Nigam", "Council", "Ministry", "Govt", "BSNL", "IIT", "AIIMS", "NCSM", "FACT", "IIMIDR", "IISER", "DDA", "MFL", "EIL", "REIL", "MoRTH", "BSF", "DMRC", "NHPC", "CRPF", "ITBP", "JNPT", "DGLL", "NRL", "SAI", "ASI", "DU", "TMC", "IGNCA", "ALHW", "ESIC", "HWB", "NALCO", "NEHU", "IIAP", "PDIL", "THDC", "NIFT", "JMI", "GSO", "NES", "UoH", "VMHK", "IIFPT", "CVPP", "NIMSM", "JIPMP", "NCCBM", "NCPUL", "NRB", "AMSRB", "AIMNP", "NITT", "AMT", "CWC", "SPAD", "IIMU", "IIMB", "OIDB", "NIOT", "DCSEM", "NMPT", "KoPT", "NITW", "NITRK", "NECTA", "HOCL", "CSRC", "MMSME", "DGS", "NVS", "GCNEP", "DREV", "BPPI", "RRCAT", "CURAJ", "IGNOU", "NIMSME", "SA", "MGIMS", "NIFTM", "SNBNC", "CSB", "SCL", "IWAI", "JMVP", "NHDC", "ISMD", "RMLH", "IIEST", "NABI", "UoA", "GSO", "NES", "UoH", "VMHK", "IIFPT", "CVPP", "NIMSM", "JIPMP", "NCCBM", "NCPUL", "NRB", "AMSRB", "AIMNP", "NITT", "AMT", "CWC", "SPAD", "IIMU", "IIMB", "OIDB", "NIOT", "DCSEM", "NMPT", "KoPT", "NITW", "NITRK", "NECTA", "HOCL", "CSRC", "MMSME", "DGS", "NVS", "GCNEP", "DREV", "BPPI", "RRCAT", "CURAJ", "IGNOU", "NIMSME"]


def parse_tender_blocks_from_tagged_file(file_path: Path) -> List[str]:
    """Reads the file and splits it into tagged tender blocks using delimiters."""
    # (No changes needed in this function)
    if not file_path.is_file():
        print(f"[Filter Engine] ERROR: Tender source file not found at {file_path}")
        return []
    try: content = file_path.read_text(encoding="utf-8", errors='ignore')
    except Exception as e: print(f"[Filter Engine] ERROR: Failed to read file {file_path}: {e}"); return []
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
    Maps extracted data to keys expected by the dashboard template. Includes Link.
    """
    # print("\n[Filter Engine] --- EXTRACTING FROM BLOCK ---") # Optional Debug
    # print(block_text[:500] + "..." if len(block_text) > 500 else block_text)
    # print("[Filter Engine] -----------------------------")

    tender: Dict[str, Any] = {
        "start_date": "N/A", "end_date": "N/A", "opening_date": "N/A",
        "title": "N/A", "tender_id": "N/A", "department": "N/A", "state": "N/A",
        "link": "N/A", # Added link field
    }

    # Extract Dates
    try:
        dates = TAG_REGEX["Date"].findall(block_text)
        # print(f"[Filter Engine] DEBUG Found Dates: {dates}")
        if len(dates) > 0: tender["start_date"] = dates[0].strip()
        if len(dates) > 1: tender["end_date"] = dates[1].strip()
        if len(dates) > 2: tender["opening_date"] = dates[2].strip()
    except Exception as e: print(f"[Filter Engine] ERROR extracting Dates: {e}")

    # Extract Title
    try:
        title_match = TAG_REGEX["Title"].search(block_text)
        # print(f"[Filter Engine] DEBUG Title Match: {title_match}")
        if title_match: tender["title"] = title_match.group(1).strip()
    except Exception as e: print(f"[Filter Engine] ERROR extracting Title: {e}")

    # Extract ID
    try:
        id_match = TAG_REGEX["ID"].search(block_text)
        # print(f"[Filter Engine] DEBUG ID Match: {id_match}")
        if id_match: tender["tender_id"] = id_match.group(1).strip()
    except Exception as e: print(f"[Filter Engine] ERROR extracting ID: {e}")

    # Extract Department
    try:
        dept_match = TAG_REGEX["Department"].search(block_text)
        # print(f"[Filter Engine] DEBUG Department Match: {dept_match}")
        if dept_match: tender["department"] = dept_match.group(1).strip()
    except Exception as e: print(f"[Filter Engine] ERROR extracting Department: {e}")

    # --- ADDED: Extract Link ---
    try:
        link_match = TAG_REGEX["Link"].search(block_text)
        # print(f"[Filter Engine] DEBUG Link Match: {link_match}")
        if link_match: tender["link"] = link_match.group(1).strip()
    except Exception as e: print(f"[Filter Engine] ERROR extracting Link: {e}")
    # --- End Link Extraction ---

    # Extract State from Department text
    if tender["department"] != "N/A":
        try:
            for state_name in INDIAN_STATES:
                if re.search(r'\b' + re.escape(state_name) + r'\b', tender["department"], re.IGNORECASE):
                    tender["state"] = state_name
                    break
        except Exception as e: print(f"[Filter Engine] ERROR extracting State: {e}")

    # print(f"[Filter Engine] DEBUG Resulting Tender Dict: {tender}")
    return tender


def matches_filters(tender: Dict[str, Any], keywords: List[str], use_regex: bool, state_filter: Optional[str], start_date_str: Optional[str], end_date_str: Optional[str]) -> bool:
    """Checks if a parsed tender dictionary matches the filter criteria."""
    # State Filter
    if state_filter and state_filter.lower() not in tender.get("state", "N/A").lower():
        return False

    # Date Filtering
    tender_date_format = "%d-%b-%Y" # Adjusted based on previous refinement
    filter_date_format = "%Y-%m-%d"
    tender_publish_date = None
    tender_publish_date_str = tender.get("start_date", "")
    if tender_publish_date_str and tender_publish_date_str != "N/A":
        try: tender_publish_date = datetime.strptime(tender_publish_date_str.split(" ")[0], tender_date_format).date() # Parse only date part
        except ValueError: print(f"[Filter Engine] WARNING: Could not parse ePublish Date '{tender_publish_date_str}' for filtering.")

    if start_date_str and tender_publish_date:
        try: filter_start_date = datetime.strptime(start_date_str, filter_date_format).date();
        if tender_publish_date < filter_start_date: return False
        except ValueError: pass
    if end_date_str and tender_publish_date:
        try: filter_end_date = datetime.strptime(end_date_str, filter_date_format).date();
        if tender_publish_date > filter_end_date: return False
        except ValueError: pass

    # Keyword Filter - ADDED 'link' to searched fields
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
    print("--- Running Filter (Engine v3.3: Extracts Link Tag) ---")
    # ... (rest of function is identical, calls updated extract_tender_info_from_tagged_block) ...
    print(f"  Source File: {tender_filename}")
    print(f"  Keywords: {keywords} (Regex: {use_regex})")
    print(f"  State: {state or 'Any'}")
    print(f"  Start Date: {start_date or 'None'}")
    print(f"  End Date: {end_date or 'None'}")
    print(f"  Filter Name: {filter_name}")
    print("-----------------------------------------------------")

    tender_path = base_folder / tender_filename
    tagged_blocks = parse_tender_blocks_from_tagged_file(tender_path)
    if not tagged_blocks: print("[Filter Engine] WARNING: No tender blocks parsed.")

    matching_tender_dictionaries: List[Dict[str, Any]] = []
    processed_count = 0; match_count = 0
    for block_text in tagged_blocks:
        processed_count += 1
        tender_info = extract_tender_info_from_tagged_block(block_text)
        if matches_filters(tender_info, keywords, use_regex, state, start_date, end_date):
            matching_tender_dictionaries.append(tender_info)
            match_count += 1

    print(f"[Filter Engine] Processed {processed_count} blocks, found {match_count} matching tenders.")
    output_folder = base_folder / "Filtered Tenders" / f"{filter_name} Tenders"
    output_folder.mkdir(parents=True, exist_ok=True)
    output_filename = "Filtered_Tenders.json"
    output_path = output_folder / output_filename
    try:
        print(f"[Filter Engine] Saving {match_count} matched tender dictionaries to: {output_path}")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(matching_tender_dictionaries, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[Filter Engine] ERROR: Failed to write output JSON file {output_path}: {e}")
        raise IOError(f"Failed to write output JSON file: {e}") from e
    return str(output_path.resolve())

# --- END OF FILE TenFin-main/filter_engine.py ---
