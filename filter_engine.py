import os
import re
from datetime import datetime

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

def parse_tender_blocks(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    blocks = []
    current_block = []

    for line in lines:
        if TENDER_BLOCK_PATTERN.match(line.strip()):
            if current_block:
                blocks.append(current_block)
            current_block = [line.strip()]
        else:
            current_block.append(line.strip())

    if current_block:
        blocks.append(current_block)

    print("TOTAL BLOCKS PARSED:", len(blocks))
    for block in blocks:
        print("\n".join(block))
        print("-" * 50)

    return blocks

def extract_tender_info(block):
    tender = {
        "start_date": "",
        "end_date": "",
        "opening_date": "",
        "title": "",
        "tender_id": "",
        "department": "",
        "state": ""
    }

    date_lines = block[:3]
    tender["start_date"] = date_lines[0] if len(date_lines) > 0 else ""
    tender["end_date"] = date_lines[1] if len(date_lines) > 1 else ""
    tender["opening_date"] = date_lines[2] if len(date_lines) > 2 else ""

    for line in block:
        if line.startswith("[") and "]" in line:
            if not tender["title"]:
                tender["title"] = line.strip("[]")
            elif "tender" in line.lower():
                tender["tender_id"] = line.strip("[]")
        if "department" in line.lower():
            tender["department"] = line
        if any(state.lower() in line.lower() for state in INDIAN_STATES):
            tender["state"] = line.strip()

    print("TENDER EXTRACTED:", tender)
    return tender

def matches_filters(tender, keywords, use_regex, state, start_date, end_date):
    if state and state.lower() not in tender["state"].lower():
        return False

    if start_date:
        try:
            tender_start = datetime.strptime(tender["start_date"], "%d-%m-%Y")
            filter_start = datetime.strptime(start_date, "%Y-%m-%d")
            if tender_start < filter_start:
                return False
        except Exception as e:
            print("Start date parse error:", e)

    if end_date:
        try:
            tender_end = datetime.strptime(tender["end_date"], "%d-%m-%Y")
            filter_end = datetime.strptime(end_date, "%Y-%m-%d")
            if tender_end > filter_end:
                return False
        except Exception as e:
            print("End date parse error:", e)

    if keywords:
        content = " ".join(tender.values())
        if use_regex:
            try:
                return any(re.search(kw, content, re.IGNORECASE) for kw in keywords)
            except re.error as e:
                print("Regex error:", e)
                return False
        else:
            return any(kw.lower() in content.lower() for kw in keywords)

    return True

def run_filter(base_folder, tender_filename, keywords, use_regex, filter_name, state, start_date, end_date):
    print("=== FILTER CONFIG ===")
    print("Keywords:", keywords)
    print("Regex?:", use_regex)
    print("State Filter:", state)
    print("Start Date:", start_date)
    print("End Date:", end_date)
    print("======================")

    tender_path = os.path.join(base_folder, tender_filename)
    blocks = parse_tender_blocks(tender_path)

    filtered_blocks = []

    for block in blocks:
        tender = extract_tender_info(block)
        if matches_filters(tender, keywords, use_regex, state, start_date, end_date):
            print("✅ MATCHED:", tender["title"])
            filtered_blocks.append("\n".join(block))
        else:
            print("❌ NOT MATCHED:", tender["title"])

    output_folder = os.path.join(base_folder, "Filtered Tenders", f"{filter_name} Tenders")
    os.makedirs(output_folder, exist_ok=True)

    output_path = os.path.join(output_folder, "Filtered_Tenders.txt")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(filtered_blocks))

    return output_path
