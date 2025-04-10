import os
import re
from typing import List

TENDER_START_PATTERN = re.compile(r"^\d+\.\s*$")

def match_block(block_lines: List[str], keywords: List[str], use_regex: bool) -> List[str]:
    matches = []
    for line in block_lines:
        for pattern in keywords:
            flags = re.IGNORECASE
            if use_regex:
                if re.search(pattern, line, flags):
                    matches.append(pattern)
            else:
                if pattern.lower() in line.lower():
                    matches.append(pattern)
    return list(set(matches))

def highlight_line(line: str, matches: List[str], use_regex: bool) -> str:
    for m in matches:
        try:
            if use_regex:
                line = re.sub(f"({m})", r">>>\1<<<", line, flags=re.IGNORECASE)
            else:
                pattern = re.escape(m)
                line = re.sub(f"({pattern})", r">>>\1<<<", line, flags=re.IGNORECASE)
        except re.error:
            continue
    return line

def run_filter(
    base_folder: str,
    tender_filename: str,
    keywords: List[str],
    use_regex: bool,
    filter_name: str
) -> str:
    selected_file = os.path.join(base_folder, tender_filename)
    if not os.path.exists(selected_file):
        raise FileNotFoundError(f"Tender file not found: {selected_file}")

    filtered_dir = os.path.join(base_folder, "Filtered Tenders")
    subdir_name = f"{filter_name} Tenders"
    output_path = os.path.join(filtered_dir, subdir_name)
    os.makedirs(output_path, exist_ok=True)
    output_file = os.path.join(output_path, "Filtered_Tenders.txt")

    filtered_blocks = []
    current_block = []

    with open(selected_file, "r", encoding="utf-8") as infile:
        for line in infile:
            if TENDER_START_PATTERN.match(line):
                if current_block:
                    matched = match_block(current_block, keywords, use_regex)
                    if matched:
                        highlighted = [highlight_line(l, matched, use_regex) for l in current_block]
                        filtered_blocks.append("".join(highlighted) + "\n")
                current_block = [line]
            else:
                current_block.append(line)

        if current_block:
            matched = match_block(current_block, keywords, use_regex)
            if matched:
                highlighted = [highlight_line(l, matched, use_regex) for l in current_block]
                filtered_blocks.append("".join(highlighted))

    with open(output_file, "w", encoding="utf-8") as outfile:
        outfile.writelines(filtered_blocks)

    return output_file

