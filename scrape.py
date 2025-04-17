#!/usr/bin/env python3

import asyncio
import datetime
import logging
import re
from pathlib import Path
from typing import Tuple, Optional, Dict, Set, List

from bs4 import BeautifulSoup, Tag
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

# === CONFIGURATION ===
try:
    SCRIPT_DIR = Path(__file__).parent.resolve()
except NameError:
    SCRIPT_DIR = Path('.').resolve()
    print(f"Warning: __file__ not defined, using current directory as SCRIPT_DIR: {SCRIPT_DIR}")

BASE_DATA_DIR = SCRIPT_DIR / "scraped_data"
RAW_PAGES_DIR = BASE_DATA_DIR / "RawPages"
LOG_DIR = SCRIPT_DIR / "logs"

BASE_URL = "https://eprocure.gov.in/eprocure/app?component=%24TablePages.linkPage&page=FrontEndAdvancedSearchResult&service=direct&session=T&sp=AFrontEndAdvancedSearchResult%2Ctable&sp={}"
MAX_PAGES_TO_FETCH = 150
RETRY_LIMIT = 3
CONCURRENCY = 10
PAGE_LOAD_TIMEOUT = 20000

# === LOG CONFIG ===
LOG_FILE = LOG_DIR / "scrape.log"
TODAY_STR = datetime.datetime.now().strftime("%Y-%m-%d")

LOG_DIR.mkdir(parents=True, exist_ok=True)
BASE_DATA_DIR.mkdir(parents=True, exist_ok=True)
RAW_PAGES_DIR.mkdir(parents=True, exist_ok=True)

def ensure_date_header():
    if LOG_FILE.exists():
        try:
            with open(LOG_FILE, "r", encoding='utf-8') as f:
                if f"======== {TODAY_STR} ========" in f.read(): return
        except Exception as e: print(f"Warning: Could not read log file {LOG_FILE}: {e}")
    try:
        with open(LOG_FILE, "a", encoding='utf-8') as f: f.write(f"\n\n======== {TODAY_STR} ========\n")
    except Exception as e: print(f"Warning: Could not write header to log file {LOG_FILE}: {e}")

ensure_date_header()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[ logging.FileHandler(LOG_FILE, encoding='utf-8'), logging.StreamHandler() ]
)

# --- Regex Definitions ---
# 1. Finds content inside square brackets (non-greedy)
BRACKET_CONTENT_REGEX = re.compile(r"\[(.*?)\]")
# 2. STRICTLY matches the required ID format: 2025_WORD_NUM_NUM
#    Uses ^ and $ for exact match of the *content* inside brackets.
STRICT_ID_CONTENT_REGEX = re.compile(r"^2025_\w+_\d+_\d+$")

def get_safe_text(element: Optional[Tag], default="N/A") -> str:
    return element.get_text(strip=True) if element else default

def natural_sort_key(filename: str) -> int:
    match = re.search(r"(\d+)", filename)
    return int(match.group(1)) if match else 0


# === REVISED fetch_single_page with STRICT Single Bracket ID Logic ===
async def fetch_single_page(page, page_number) -> Tuple[int, Optional[str]]:
    """Fetches page, parses HTML table, extracts tagged data using strict ID logic."""
    url = BASE_URL.format(page_number)
    main_page_url = "https://eprocure.gov.in/eprocure/app"

    for attempt in range(1, RETRY_LIMIT + 1):
        tagged_page_content = ""
        try:
            logging.info(f"📄 Fetching Page {page_number} (Attempt {attempt}/{RETRY_LIMIT})")
            await page.goto(main_page_url, wait_until="networkidle", timeout=PAGE_LOAD_TIMEOUT)
            await page.goto(url, wait_until="networkidle", timeout=PAGE_LOAD_TIMEOUT)

            content = await page.content()
            if not content:
                 logging.warning(f"  ⚠️ Page {page_number} content is empty.")
                 continue

            soup = BeautifulSoup(content, "html.parser")
            tender_table = soup.find("table", id="table")

            if not tender_table:
                body_text_lower = soup.body.get_text(separator=' ', strip=True).lower() if soup.body else ""
                if "no records found" in body_text_lower or "no tenders available" in body_text_lower:
                    return page_number, "--- NO RECORDS ---"
                logging.warning(f"  ⚠️ Could not find table with id='table' on page {page_number}. Skipping page.")
                return page_number, None

            tender_rows = tender_table.find_all("tr", id=re.compile(r"informal"))
            logging.debug(f"  Found {len(tender_rows)} tender rows in table on page {page_number}.")

            if not tender_rows:
                 if "No Records Found" in soup.get_text() or "No Tenders Available" in soup.get_text():
                     return page_number, "--- NO RECORDS ---"
                 else:
                     logging.warning(f"  ⚠️ Found table but no tender rows (tr with id~='informal') on page {page_number}.")
                     return page_number, None

            for row in tender_rows:
                cols = row.find_all("td")
                if len(cols) < 6: continue

                serial_no = get_safe_text(cols[0])
                epub_date = get_safe_text(cols[1])
                closing_date = get_safe_text(cols[2])
                opening_date = get_safe_text(cols[3])
                org_chain = get_safe_text(cols[5])
                title_id_cell = cols[4]

                title = "N/A"
                tender_id_content = "N/A" # Store the valid ID content, default N/A
                found_id_content = ""     # Temp store for matched ID content
                found_id_bracket = ""     # Temp store for the full bracket if ID found

                cell_text = title_id_cell.get_text(separator='\n', strip=True)

                # --- New Strict ID Logic ---
                # Find *all* bracketed contents in the cell
                all_brackets = BRACKET_CONTENT_REGEX.findall(cell_text)
                for content_inside_bracket in all_brackets:
                    content_inside_bracket = content_inside_bracket.strip()
                    # Check if this specific content matches the strict ID format
                    if STRICT_ID_CONTENT_REGEX.match(content_inside_bracket):
                        found_id_content = content_inside_bracket
                        found_id_bracket = f"[{content_inside_bracket}]" # Store the bracket too
                        tender_id_content = found_id_content # Assign the valid content
                        # print(f"DEBUG: Found Strict ID: {tender_id_content}") # Optional Debug
                        break # Found the ID, stop checking brackets for ID

                # --- Determine Title ---
                # Prioritize link text
                link_tag = title_id_cell.find("a")
                if link_tag:
                    title = link_tag.get_text(strip=True)
                    # If link text IS the ID we found, reset title to N/A (to find it elsewhere)
                    if found_id_content and title == found_id_bracket:
                         title = "N/A"

                # If title still N/A, look for the *first* bracketed content that is *not* the found ID
                if title == "N/A":
                    for content_inside_bracket in all_brackets:
                         content_inside_bracket = content_inside_bracket.strip()
                         current_bracket = f"[{content_inside_bracket}]"
                         # Ensure it's not the ID bracket and has some content
                         if content_inside_bracket and current_bracket != found_id_bracket:
                             title = content_inside_bracket
                             # print(f"DEBUG: Found Title in brackets: {title}") # Optional Debug
                             break # Found first suitable bracket for title

                # Final fallback if title is still N/A
                if title == "N/A":
                    first_line = cell_text.split('\n')[0]
                    # Assign if it's not the ID bracket and not empty
                    if first_line and first_line != found_id_bracket:
                        title = first_line
                        # print(f"DEBUG: Found Title as first line: {title}") # Optional Debug

                # Construct tagged block
                tagged_block = (
                    f"{serial_no}\n"
                    f"<Date>{epub_date}</Date>\n"
                    f"<Date>{closing_date}</Date>\n"
                    f"<Date>{opening_date}</Date>\n"
                    f"<Title>{title}</Title>\n"
                    f"<ID>{tender_id_content}</ID>\n" # Use the validated content or N/A
                    f"<Department>{org_chain}</Department>\n"
                )
                tagged_page_content += "--- TENDER START ---\n" + tagged_block + "--- TENDER END ---\n\n"

            if not tagged_page_content:
                 logging.warning(f"  ⚠️ No tenders extracted from rows on page {page_number}, though rows were found.")
                 return page_number, None

            logging.info(f"  ✅ Page {page_number} processed successfully (HTML parse).")
            return page_number, tagged_page_content.strip()

        except PlaywrightTimeout:
            logging.warning(f"  ⚠️ Timeout ({PAGE_LOAD_TIMEOUT}ms) on Page {page_number}, attempt {attempt}.")
        except Exception as e:
            logging.error(f"  ❌ Error fetching/processing Page {page_number}, attempt {attempt}: {type(e).__name__} - {e}")
            import traceback
            logging.error(traceback.format_exc())

        if attempt < RETRY_LIMIT:
            wait_time = 2 ** attempt
            logging.info(f"  Retrying page {page_number} in {wait_time} seconds...")
            await asyncio.sleep(wait_time)

    logging.error(f"  ❌ Failed to process Page {page_number} after {RETRY_LIMIT} attempts.")
    return page_number, None


# --- fetch_pages_concurrently, merge_and_cleanup, scrape_all_pages ---
# (No changes needed in these functions from the previous 'tagged' version)
async def fetch_pages_concurrently(playwright):
    # ... (identical to previous version) ...
    browser = await playwright.chromium.launch(headless=True)
    all_page_results: Dict[int, str] = {}
    try:
        pages = await asyncio.gather(*[browser.new_page() for _ in range(CONCURRENCY)])
        logging.info(f"Launched {CONCURRENCY} browser pages for concurrent fetching.")
        last_valid_content_hash = None
        stop_fetching = False
        current_page_num = 1
        while current_page_num <= MAX_PAGES_TO_FETCH and not stop_fetching:
            tasks = []
            batch_start_page = current_page_num
            for i in range(CONCURRENCY):
                if current_page_num > MAX_PAGES_TO_FETCH: break
                tasks.append(fetch_single_page(pages[i], current_page_num))
                current_page_num += 1
            if not tasks: break
            logging.info(f"🚀 Fetching batch: Pages {batch_start_page} to {current_page_num - 1}")
            results = await asyncio.gather(*tasks)
            for page_number, tagged_content in results:
                if tagged_content is None:
                    logging.warning(f"  ⚠️ Page {page_number} permanently failed in batch.")
                    continue
                if tagged_content == "--- NO RECORDS ---":
                    logging.info(f"🛑 Stopping: 'No Records Found' detected on page {page_number}.")
                    stop_fetching = True; break
                current_content_hash = hash(tagged_content)
                if last_valid_content_hash is not None and current_content_hash == last_valid_content_hash:
                     logging.info(f"🛑 Stopping: Duplicate content detected on page {page_number}.")
                     stop_fetching = True; break
                save_path = RAW_PAGES_DIR / f"Page_{page_number}.txt"
                try:
                    save_path.write_text(tagged_content, encoding="utf-8")
                    all_page_results[page_number] = "Saved"
                    last_valid_content_hash = current_content_hash
                    logging.debug(f"  Saved intermediate tagged file: {save_path}")
                except OSError as e:
                    logging.error(f"  ❌ Failed to save intermediate file {save_path}: {e}")
            if stop_fetching: break
    finally:
        if browser:
            logging.info("Closing browser.")
            await browser.close()
    logging.info(f"Fetching complete. Saved {len(all_page_results)} intermediate tagged page files.")
    return all_page_results


async def merge_and_cleanup() -> Tuple[int, Optional[Path]]:
    # ... (identical to previous version) ...
    today_filename_str = datetime.datetime.now().strftime("%Y-%m-%d")
    final_output_path = BASE_DATA_DIR / f"Final_Tender_List_{today_filename_str}.txt"
    page_files_count = 0
    merged_count = 0
    seen_content_hashes: Set[int] = set()
    logging.info(f"Merging unique tagged pages into: {final_output_path}")
    logging.info(f"Looking for raw pages in: {RAW_PAGES_DIR}")
    if not RAW_PAGES_DIR.is_dir():
        logging.warning(f"Raw pages directory '{RAW_PAGES_DIR}' not found.")
        return 0, None
    try:
        page_files = sorted(
            [p for p in RAW_PAGES_DIR.glob("Page_*.txt") if p.is_file()],
            key=lambda p: natural_sort_key(p.name)
        )
        page_files_count = len(page_files)
        logging.info(f"Found {page_files_count} raw page files to process.")
    except OSError as e:
        logging.error(f"Error listing files in {RAW_PAGES_DIR}: {e}")
        return 0, None
    if not page_files:
         logging.warning(f"No 'Page_*.txt' files found in {RAW_PAGES_DIR} to merge.")
         return 0, None
    try:
        with open(final_output_path, "w", encoding="utf-8") as outfile:
            for page_path in page_files:
                try:
                    content = page_path.read_text(encoding="utf-8").strip()
                    if not content:
                         logging.warning(f"  Skipping empty file: {page_path.name}")
                         page_path.unlink(); continue
                    content_hash = hash(content)
                    if content_hash not in seen_content_hashes:
                        outfile.write(content + "\n\n")
                        seen_content_hashes.add(content_hash)
                        merged_count += 1
                        logging.debug(f"  Merged unique tagged content from: {page_path.name}")
                    else:
                        logging.info(f"🗑️ Skipping duplicate tagged content from: {page_path.name}")
                    page_path.unlink()
                    logging.debug(f"  Deleted raw file: {page_path.name}")
                except OSError as e: logging.error(f"  ❌ Error processing/deleting {page_path.name}: {e}")
                except Exception as e: logging.error(f"  ❌ Unexpected error processing file {page_path.name}: {e}")
        logging.info(f"✅ Successfully merged {merged_count} unique pages (out of {page_files_count} found) to: {final_output_path}")
        return merged_count, final_output_path
    except OSError as e:
        logging.error(f"❌ Failed to write final merged file {final_output_path}: {e}")
        return merged_count, None
    except Exception as e:
         logging.error(f"❌ Unexpected error during merge: {e}")
         return merged_count, None


async def scrape_all_pages():
     # ... (identical to previous version) ...
    start_time = datetime.datetime.now()
    merged_count = 0
    final_output_file = None
    try:
        async with async_playwright() as p:
            logging.info("🚀 Starting concurrent scrape")
            await fetch_pages_concurrently(p)
        merged_count, final_output_file = await merge_and_cleanup()
    except Exception as e:
        logging.error(f"💥 CRITICAL ERROR during scraping/merging: {type(e).__name__} - {e}")
        import traceback
        logging.error(traceback.format_exc())
    finally:
        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()
        log_status = "completed" if merged_count > 0 else "failed or produced no output"
        logging.info(f"🏁 Scrape run {log_status}.")
        logging.info(f"   Duration: {datetime.timedelta(seconds=duration)}")
        logging.info(f"   Merged {merged_count} unique pages.")
        if final_output_file: logging.info(f"   Final output: {final_output_file}")
        else: logging.warning("   Final output file was not created.")


if __name__ == "__main__":
    asyncio.run(scrape_all_pages())

# --- END OF FILE TenFin-main/scrape.py ---
