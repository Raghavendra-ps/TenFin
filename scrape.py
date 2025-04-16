#!/usr/bin/env python3

import asyncio
import datetime
import logging
import re
import subprocess
import shutil # For checking executables (which) and potentially rmtree
# Make sure os is imported if you need it for other things, but not needed for path joining here
# import os 
from pathlib import Path
from typing import Tuple, Optional, Dict, Set

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout, Error as PlaywrightError

# === CONFIGURATION ===
# --- Paths (relative to this script file using pathlib) ---
try:
    SCRIPT_DIR = Path(__file__).parent.resolve()
except NameError:
    # Fallback if __file__ is not defined (e.g., interactive interpreter)
    SCRIPT_DIR = Path('.').resolve()
    print(f"Warning: __file__ not defined, using current directory as SCRIPT_DIR: {SCRIPT_DIR}")

# These should align with directories created/used by setup.sh and dashboard.py
BASE_DATA_DIR = SCRIPT_DIR / "scraped_data"
RAW_PAGES_DIR = BASE_DATA_DIR / "RawPages" # Directory to store intermediate page files
# --- CORRECTED LOG_DIR DEFINITION using pathlib ---
LOG_DIR = SCRIPT_DIR / "logs"              # Path object for log directory

# --- Scraping Parameters ---
BASE_URL = "https://eprocure.gov.in/eprocure/app?component=%24TablePages.linkPage&page=FrontEndAdvancedSearchResult&service=direct&session=T&sp=AFrontEndAdvancedSearchResult%2Ctable&sp={}"
MAX_PAGES_TO_FETCH = 150  # Max pages to attempt fetching
CONCURRENT_FETCHES = 5    # Number of pages to fetch in parallel (adjust based on resources/network)
PAGE_TIMEOUT = 30000      # Timeout for page navigation/loading in milliseconds (30s)
RETRY_LIMIT = 3           # Number of retries for a failed page fetch

# --- Logging Configuration ---
# LOG_FILE definition now works correctly because LOG_DIR is a Path object
LOG_FILE = LOG_DIR / "scrape.log"
TODAY_DATE_STR = datetime.datetime.now().strftime("%Y-%m-%d")

# === Setup Logging ===
def setup_logging():
    """Configures logging to file and console."""
    try:
        # Use the LOG_DIR Path object's mkdir method
        LOG_DIR.mkdir(parents=True, exist_ok=True) # Ensure log directory exists

        # Use the LOG_FILE Path object here
        log_needs_header = not LOG_FILE.exists()
        if LOG_FILE.exists():
            try:
                # Use Path object's read_text method (or open)
                content = LOG_FILE.read_text(encoding="utf-8")
                if f"======== {TODAY_DATE_STR} ========" not in content:
                    log_needs_header = True
            except Exception as e:
                 print(f"Warning: Could not read log file {LOG_FILE} to check header: {e}")
                 log_needs_header = True # Add header just in case

        log_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

        # File Handler (Append Mode) - logging handlers accept Path objects directly
        file_handler = logging.FileHandler(LOG_FILE, mode='a', encoding='utf-8')
        file_handler.setFormatter(log_formatter)

        # Console Handler
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(log_formatter)

        # Configure root logger
        logging.basicConfig(level=logging.INFO, handlers=[file_handler, stream_handler])

        # Write header if needed
        if log_needs_header:
             logging.info(f"\n======== {TODAY_DATE_STR} ========") # Use logging to write header

    except Exception as e:
        print(f"CRITICAL: Failed to set up logging: {e}")
        # Depending on severity, you might want to exit or raise
        # raise RuntimeError("Logging setup failed") from e


# === Text Cleaning ===
# List of exact text phrases to remove from the scraped content
UNWANTED_TEXT = [
    "eProcurement System Government of Punjab", "eProcurement System", "<<", "<", ">", ">>",
    "Visitor No:", # Remove visitor count variations
    "Designed, Developed and Hosted by", "National Informatics Centre",
    "Version :", # Remove version variations
    "(c) 2017 Tenders NIC, All rights reserved.",
    "Site best viewed in IE 10 and above", "Portal policies", "|", "«", "»",
    "Screen Reader Access", "Search", "Active Tenders", "Tenders by Closing Date",
    "Corrigendum", "Results of Tenders", "Deployment of New Digital Signing",
    "Bidder Registration Charges", "NEFT / RTGS Mode", "Payment of Online Fees",
    "MIS Reports", "Tenders by Location", "Tenders by Organisation",
    "Tenders by Classification", "Tenders in Archive", "Tenders Status",
    "Cancelled/Retendered", "Downloads", "Debarment List", "Announcements",
    "Recognitions", "Site compatibility", "Back"
]
# Regex to remove lines containing only whitespace or digits (like page numbers)
EMPTY_OR_NUMERIC_LINE_PATTERN = re.compile(r"^\s*\d*\s*$")
# Regex to remove timestamp/version strings like '1.09.21 06-Nov-2024'
VERSION_DATE_PATTERN = re.compile(r"\d{1,2}\.\d{1,2}\.\d{1,2}\s+\d{1,2}-[A-Za-z]{3}-\d{4}")

def clean_text(text: str) -> str:
    """Removes predefined unwanted text and excessive newlines."""
    # Remove specific phrases first
    for junk in UNWANTED_TEXT:
        text = text.replace(junk, "")

    # Remove version/date strings
    text = VERSION_DATE_PATTERN.sub("", text)

    # Split into lines, process each line, and rejoin
    lines = text.splitlines()
    cleaned_lines = []
    for line in lines:
        stripped_line = line.strip()
        # Remove lines that are empty, just digits, or just visitor numbers after stripping
        if stripped_line and not EMPTY_OR_NUMERIC_LINE_PATTERN.match(stripped_line) and not stripped_line.startswith("Visitor No:"):
             cleaned_lines.append(stripped_line)

    # Rejoin lines with single newlines and remove multi-newlines that might form
    text = "\n".join(cleaned_lines)
    text = re.sub(r"\n{2,}", "\n", text).strip() # Collapse multiple newlines to one
    return text


# === Helper for Sorting Filenames ===
def natural_sort_key(filename: str) -> int:
    """Extracts the first number from a filename for natural sorting."""
    match = re.search(r"(\d+)", filename)
    # Return the number found, or a large number if no number is found
    # so files without numbers sort last. Use 999999 as a large number.
    return int(match.group(1)) if match else 999999


# === Scraping Functions ===
async def fetch_single_page(page: 'Page', page_number: int) -> Tuple[int, Optional[str]]:
    """Fetches and cleans content of a single page number with retries."""
    url = BASE_URL.format(page_number)
    logging.info(f"Attempting to fetch Page {page_number} -> {url}")

    for attempt in range(1, RETRY_LIMIT + 1):
        try:
            logging.debug(f"  [Page {page_number}, Attempt {attempt}/{RETRY_LIMIT}] Navigating...")
            await page.goto(url, wait_until="networkidle", timeout=PAGE_TIMEOUT) # networkidle waits for network activity to cease

            content = await page.content()
            if not content:
                 logging.warning(f"  [Page {page_number}, Attempt {attempt}] Received empty content.")
                 continue # Try again

            soup = BeautifulSoup(content, "html.parser")
            raw_text = soup.get_text(separator="\n", strip=False) # Get text with basic structure
            cleaned_text = clean_text(raw_text)

            logging.info(f"  [Page {page_number}, Attempt {attempt}] Fetch successful.")
            return page_number, cleaned_text

        except PlaywrightTimeout:
            logging.warning(f"  [Page {page_number}, Attempt {attempt}] Timeout error after {PAGE_TIMEOUT}ms.")
        except PlaywrightError as e:
            # More specific Playwright errors if needed
            logging.error(f"  [Page {page_number}, Attempt {attempt}] Playwright error: {type(e).__name__} - {e}")
        except Exception as e:
            logging.error(f"  [Page {page_number}, Attempt {attempt}] Unexpected error: {type(e).__name__} - {e}")

        if attempt < RETRY_LIMIT:
            await asyncio.sleep(2 ** attempt) # Exponential backoff (2, 4, 8 seconds...)
        else:
            logging.error(f"❌ Failed to fetch Page {page_number} after {RETRY_LIMIT} attempts.")

    return page_number, None # Return None if all retries fail


async def fetch_pages_concurrently(playwright: 'Playwright') -> Dict[int, str]:
    """Manages concurrent fetching of multiple pages."""
    browser = None
    all_fetched_content: Dict[int, str] = {}
    last_valid_content_hash = None
    stop_fetching = False
    current_page_num = 1

    try:
        browser = await playwright.chromium.launch(headless=True)
        # context = await browser.new_context() # Optional: Use context for isolation

        while current_page_num <= MAX_PAGES_TO_FETCH and not stop_fetching:
            tasks = []
            batch_start_page = current_page_num
            pages_in_batch = []

            # Prepare batch of tasks
            for i in range(CONCURRENT_FETCHES):
                if current_page_num > MAX_PAGES_TO_FETCH:
                    break

                page = await browser.new_page()
                pages_in_batch.append(page) # Keep track to close later
                tasks.append(fetch_single_page(page, current_page_num))
                current_page_num += 1

            if not tasks: break # No more pages to fetch

            logging.info(f"🚀 Fetching batch: Pages {batch_start_page} to {current_page_num - 1}")
            results = await asyncio.gather(*tasks)

            # Close pages used in this batch
            for page in pages_in_batch:
                await page.close()

            # Process results of the batch
            for page_number, content in results:
                if content is None:
                    logging.warning(f"⚠️ Page {page_number} failed permanently in batch.")
                    continue # Skip this failed page

                # --- Stopping Conditions ---
                if "No Records Found" in content or "No Tenders Available" in content:
                     logging.info(f"🛑 Stopping: 'No Records Found' detected on page {page_number}.")
                     stop_fetching = True
                     break
                if len(content) < 100: # Adjust threshold as needed
                     logging.info(f"🛑 Stopping: Content too short ({len(content)} chars) on page {page_number}. Assuming end or error.")
                     stop_fetching = True
                     break
                current_content_hash = hash(content)
                if last_valid_content_hash is not None and current_content_hash == last_valid_content_hash:
                     logging.info(f"🛑 Stopping: Duplicate content detected on page {page_number} (same as previous valid page).")
                     stop_fetching = True
                     break

                # --- Save Valid Content ---
                logging.debug(f"  Saving content for page {page_number}")
                # Use the RAW_PAGES_DIR Path object
                save_path = RAW_PAGES_DIR / f"Page_{page_number}.txt"
                try:
                    # Use Path object's write_text method (or open)
                    save_path.write_text(content, encoding="utf-8")
                    all_fetched_content[page_number] = content
                    last_valid_content_hash = current_content_hash # Update hash only on successful save
                except OSError as e:
                    logging.error(f"❌ Failed to save Page {page_number} to {save_path}: {e}")
                    # stop_fetching = True # Optional: stop if saving fails
                    # break

            if stop_fetching:
                 logging.info("Stop condition met, ending fetch loop.")
                 break

    except Exception as e:
        logging.error(f"💥 Unexpected error during concurrent fetching: {type(e).__name__} - {e}")
        import traceback
        logging.error(traceback.format_exc())
    finally:
        if browser:
            await browser.close()
            logging.info("Browser closed.")

    return all_fetched_content


# === Merging and Cleanup ===
async def merge_and_cleanup() -> Tuple[int, Optional[Path]]:
    """Merges unique page content into a final file and cleans up raw files."""
    today_filename_str = datetime.datetime.now().strftime("%Y-%m-%d") # Use YYYY-MM-DD for better sorting
    # Use BASE_DATA_DIR Path object
    final_output_path = BASE_DATA_DIR / f"Final_Tender_List_{today_filename_str}.txt"
    page_files_count = 0
    merged_count = 0
    seen_content_hashes: Set[int] = set()

    logging.info(f"Merging unique pages into: {final_output_path}")
    logging.info(f"Looking for raw pages in: {RAW_PAGES_DIR}")

    # Use RAW_PAGES_DIR Path object
    if not RAW_PAGES_DIR.is_dir():
        logging.warning(f"Raw pages directory '{RAW_PAGES_DIR}' not found. Nothing to merge.")
        return 0, None

    # List and sort page files naturally by page number
    try:
        # Use Path object's glob method
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
        logging.info("No raw page files found matching 'Page_*.txt'.")
        return 0, None

    try:
        # Use Path object with open
        with open(final_output_path, "w", encoding="utf-8") as outfile:
            for page_path in page_files: # page_path is already a Path object from glob
                try:
                    content = page_path.read_text(encoding="utf-8")
                    content_hash = hash(content)

                    if content and content_hash not in seen_content_hashes:
                        # Add separator indicating original page number
                        outfile.write(f"======== Start of Content from Page {page_path.stem.split('_')[-1]} ========\n\n")
                        outfile.write(content + "\n\n")
                        outfile.write(f"======== End of Content from Page {page_path.stem.split('_')[-1]} ========\n\n")
                        seen_content_hashes.add(content_hash)
                        merged_count += 1
                        logging.debug(f"  Merged unique content from: {page_path.name}")
                    elif not content:
                        logging.warning(f"  Skipping empty file: {page_path.name}")
                    else:
                        logging.info(f"  Skipping duplicate content from: {page_path.name}")

                    # Delete the individual page file after processing using Path object's unlink
                    page_path.unlink()

                except OSError as e:
                    logging.error(f"  Error processing or deleting {page_path.name}: {e}")
                except Exception as e:
                     logging.error(f"  Unexpected error processing file {page_path.name}: {e}")

        logging.info(f"✅ Successfully merged {merged_count} unique pages (out of {page_files_count} found) to: {final_output_path}")
        return merged_count, final_output_path

    except OSError as e:
        logging.error(f"❌ Failed to write final merged file {final_output_path}: {e}")
        return merged_count, None # Return count processed so far, but None for path
    except Exception as e:
        logging.error(f"❌ Unexpected error during merge process: {e}")
        return merged_count, None


# === Main Orchestration ===
async def main():
    """Main function to run the scraping process."""
    setup_logging() # Ensure logging is ready
    start_time = datetime.datetime.now()
    logging.info(f"===== Scraper Run Starting: {start_time.strftime('%Y-%m-%d %H:%M:%S')} =====")
    logging.info(f"Saving raw pages to: {RAW_PAGES_DIR}")
    logging.info(f"Saving final list to: {BASE_DATA_DIR}")
    logging.info(f"Log file: {LOG_FILE}")

    merged_pages_count = 0
    final_output_file: Optional[Path] = None
    success = False
    status_message = "Scraper started."

    try:
        # Ensure raw pages directory exists using Path object's mkdir
        RAW_PAGES_DIR.mkdir(parents=True, exist_ok=True)

        # --- Run Scraper ---
        async with async_playwright() as p:
            logging.info("🚀 Launching Playwright and starting concurrent fetch...")
            fetched_data = await fetch_pages_concurrently(p)
            fetched_count = len(fetched_data)
            logging.info(f"🏁 Fetching complete. Received content for {fetched_count} pages.")

        # --- Merge and Cleanup ---
        if fetched_count > 0:
             merged_pages_count, final_output_file = await merge_and_cleanup()
             if final_output_file and merged_pages_count > 0:
                 success = True
                 status_message = f"Successfully merged {merged_pages_count} unique pages."
             elif merged_pages_count == 0:
                 status_message = "Fetching completed, but no unique pages were found or merged."
                 success = False # Treat as non-success if nothing merged
             else:
                 status_message = f"Fetching completed, but merging failed. {merged_pages_count} unique pages found before failure."
                 success = False
        else:
            status_message = "Fetching completed, but no pages returned content successfully."
            success = False # No data fetched = not successful

    except Exception as e:
        logging.error(f"💥 CRITICAL ERROR in main execution: {type(e).__name__} - {e}")
        import traceback
        logging.error(traceback.format_exc())
        status_message = f"Scraper failed critically: {type(e).__name__}"
        success = False
    finally:
        end_time = datetime.datetime.now()
        duration = end_time - start_time
        logging.info(f"===== Scraper Run Finished: {end_time.strftime('%Y-%m-%d %H:%M:%S')} =====")
        logging.info(f"Duration: {duration}")
        logging.info(f"Outcome: {'Success' if success else 'Failure'}. {status_message}")
        if final_output_file:
             logging.info(f"Final Output File: {final_output_file}")


if __name__ == "__main__":
    # To run the async main function
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Script interrupted by user (KeyboardInterrupt).")
    except Exception as e:
         # Catch errors during asyncio.run() setup itself if any
         print(f"Fatal error initializing or running the async loop: {e}")
         # Log directly if logging setup failed earlier
         logging.critical(f"Fatal error initializing or running the async loop: {e}", exc_info=True)
