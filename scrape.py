#!/usr/bin/env python3

import asyncio
import os # Keep os for os.listdir and os.remove (minimal change)
import datetime
import logging
import re
import subprocess
from pathlib import Path # Import Path
from typing import Tuple, Optional, Dict, Set # Added these for existing type hints

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout # Removed Error as PlaywrightError if not used

# === CONFIG ===
# --- Path Configuration (RELATIVE PATHS using pathlib) ---
try:
    SCRIPT_DIR = Path(__file__).parent.resolve()
except NameError:
    SCRIPT_DIR = Path('.').resolve()
    print(f"Warning: __file__ not defined, using current directory as SCRIPT_DIR: {SCRIPT_DIR}")

# Define paths relative to the script directory, consistent with setup.sh
DATA_DIR = SCRIPT_DIR / "scraped_data" # Changed from SAVE_DIR, points to the directory for pages and final list
LOG_DIR = SCRIPT_DIR / "logs"          # Changed from hardcoded path

# --- Other Config ---
BASE_URL = "https://eprocure.gov.in/eprocure/app?component=%24TablePages.linkPage&page=FrontEndAdvancedSearchResult&service=direct&session=T&sp=AFrontEndAdvancedSearchResult%2Ctable&sp={}"
MAX_PAGES = 150
RETRY_LIMIT = 3
CONCURRENCY = 10 # Kept user's value
# EMAIL variable removed

# === LOG CONFIG ===
LOG_FILE = LOG_DIR / "log.txt" # Use pathlib join
TODAY = datetime.datetime.now().strftime("%Y-%m-%d")

# Create directory if it doesn't exist using pathlib
# os.makedirs(LOG_DIR, exist_ok=True) # Old way
LOG_DIR.mkdir(parents=True, exist_ok=True) # pathlib way for logs
DATA_DIR.mkdir(parents=True, exist_ok=True) # pathlib way for data

# Check if today's header is already in the log file
def ensure_date_header():
    # Use Path object for checking existence and opening
    if LOG_FILE.exists():
        try: # Added try/except for reading log file
            with open(LOG_FILE, "r", encoding='utf-8') as f: # Use encoding
                if f"======== {TODAY} ========" in f.read():
                    return
        except Exception as e:
             # Log directly to print if logging isn't set up yet
             print(f"Warning: Could not read log file {LOG_FILE} to check header: {e}")
    try:
        with open(LOG_FILE, "a", encoding='utf-8') as f: # Use encoding
            f.write(f"\n\n======== {TODAY} ========\n")
    except Exception as e:
         print(f"Warning: Could not write header to log file {LOG_FILE}: {e}")


ensure_date_header()

# Setup logging to append to the static file
# logging handlers accept Path objects
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S", # Kept user's date format
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'), # Specify encoding
        logging.StreamHandler()
    ]
)

# === UNWANTED TEXT TO REMOVE ===
# Kept user's list exactly
UNWANTED_TEXT = [
    "eProcurement System Government of Punjab", "eProcurement System", "<<", "<", ">", ">>",
    "Visitor No:1621790", "Designed, Developed and Hosted by", "National Informatics Centre",
    "Version : 1.09.21 06-Nov-2024", "(c) 2017 Tenders NIC, All rights reserved.",
    "Site best viewed in IE 10 and above", "Portal policies", "|", "«", "Screen Reader Access",
    "Search", "Active Tenders", "Tenders by Closing Date", "Corrigendum", "Results of Tenders",
    "Deployment of New Digital Signing", "Bidder Registration Charges", "NEFT / RTGS Mode",
    "Payment of Online Fees", "MIS Reports", "Tenders by Location", "Tenders by Organisation",
    "Tenders by Classification", "Tenders in Archive", "Tenders Status", "Cancelled/Retendered",
    "Downloads", "Debarment List", "Announcements", "Recognitions", "Site compatibility", "Back"
]

# Kept user's version exactly
def natural_sort_key(filename):
    match = re.search(r"(\d+)", filename)
    return int(match.group(1)) if match else float("inf")

# Kept user's version exactly
async def fetch_single_page(page, page_number):
    url = BASE_URL.format(page_number)
    for attempt in range(1, RETRY_LIMIT + 1):
        try:
            logging.info(f"📄 Fetching Page {page_number} (Attempt {attempt})")
            await page.goto("https://eprocure.gov.in/eprocure/app", wait_until="networkidle")
            await page.goto(url, wait_until="networkidle", timeout=10000) # Kept user's timeout
            content = await page.content()
            soup = BeautifulSoup(content, "html.parser")
            text = soup.get_text(separator="\n", strip=True)

            for junk in UNWANTED_TEXT:
                text = text.replace(junk, "")
            text = re.sub(r"\n{2,}", "\n", text)

            return page_number, text

        except PlaywrightTimeout:
            logging.warning(f"⚠️ Timeout on Page {page_number}")
        except Exception as e:
            logging.error(f"❌ Error on Page {page_number}: {e}")
    return page_number, None

# Kept user's logic, adjusted save path
async def fetch_pages_concurrently(playwright):
    browser = await playwright.chromium.launch(headless=True)
    # Added try/finally block for browser closing
    try:
        pages = await asyncio.gather(*[browser.new_page() for _ in range(CONCURRENCY)])
        all_results = {}
        last_content = None
        stop = False
        current = 1

        while current <= MAX_PAGES and not stop:
            batch = []
            # Close pages from previous batch if any? No, pages are reused here implicitly.
            for i in range(CONCURRENCY):
                if current > MAX_PAGES:
                    break
                # Reusing pages from the initial gather call
                batch.append(fetch_single_page(pages[i], current))
                current += 1

            results = await asyncio.gather(*batch)
            for page_number, content in results:
                if not content or content == last_content or "No Records Found" in content or len(content.strip()) < 50:
                    logging.info(f"🛑 Stopping at Page {page_number}: Duplicate or empty.")
                    stop = True
                    break

                # --- Adjusted save_path to use DATA_DIR ---
                save_path = DATA_DIR / f"Page {page_number}.txt"
                try: # Added try/except for writing file
                    with open(save_path, "w", encoding="utf-8") as f:
                        f.write(content)
                    all_results[page_number] = content
                    last_content = content
                except OSError as e:
                     logging.error(f"❌ Failed to save page {page_number} to {save_path}: {e}")
                     # Optionally add stop = True here if saving is critical

    finally:
        if browser:
            await browser.close() # Ensure browser is closed

    return all_results

# Kept user's logic, adjusted paths and removed os.system call
async def merge_and_cleanup():
    today = datetime.datetime.now().strftime("%d-%m-%Y") # Kept user's date format
    # --- Use DATA_DIR ---
    final_path = DATA_DIR / f"Final_Tender_List {today}.txt"
    page_files = []
    try: # Added try/except for listing files
        # --- Use DATA_DIR ---
        page_files = sorted([f for f in os.listdir(DATA_DIR) if f.startswith("Page ") and f.endswith(".txt")], key=natural_sort_key)
    except OSError as e:
        logging.error(f"❌ Failed to list files in {DATA_DIR}: {e}")
        return 0, None # Return gracefully

    seen = set()
    count = 0

    if not page_files:
         logging.warning(f"No 'Page *.txt' files found in {DATA_DIR} to merge.")
         return 0, None

    try: # Added try/except for merging process
        with open(final_path, "w", encoding="utf-8") as out:
            for fname in page_files:
                # --- Use DATA_DIR ---
                path = DATA_DIR / fname
                try: # Added try/except for reading/deleting individual file
                    with open(path, "r", encoding="utf-8") as f:
                        content = f.read()
                    if content not in seen:
                        out.write(content + "\n\n")
                        seen.add(content)
                        count += 1
                    else:
                        logging.info(f"🗑️ Duplicate skipped: {fname}")
                    # os.remove(path) # Works with Path objects
                    path.unlink() # Cleaner pathlib way
                except OSError as e:
                    logging.error(f"❌ Error processing/deleting file {path}: {e}")
                except Exception as e: # Catch other potential errors reading files
                     logging.error(f"❌ Unexpected error processing file {path}: {e}")


        # --- Nextcloud os.system call REMOVED ---
        # os.system('cd /var/www/nextcloud && sudo -u www-data php occ files:scan --path="CEO/files/Artificial Intelligence"')

        logging.info(f"✅ Merged {count} pages to: {final_path}")
        return count, final_path
    except OSError as e:
        logging.error(f"❌ Failed to write final merged file {final_path}: {e}")
        return count, None # Return count processed so far, but None path
    except Exception as e:
         logging.error(f"❌ Unexpected error during merge: {e}")
         return count, None


# --- send_email function REMOVED ---
# def send_email(subject, log_file_path):
#    ... (removed) ...

# Kept user's logic, removed email call
async def scrape_all_pages():
    start_time = datetime.datetime.now()
    merged_count = 0 # Initialize count
    final_output_file = None # Initialize path
    try: # Added try block for main logic
        async with async_playwright() as p:
            logging.info("🚀 Starting concurrent scrape")
            results = await fetch_pages_concurrently(p) # results not actually used later, but keep fetch call

        merged_count, final_output_file = await merge_and_cleanup()

    except Exception as e:
        logging.error(f"💥 CRITICAL ERROR during scraping/merging: {type(e).__name__} - {e}")
        import traceback
        logging.error(traceback.format_exc())
    finally: # Ensure logging happens even on error
        end_time = datetime.datetime.now()
        duration = (end_time - start_time).seconds # Use total_seconds() for more precision if needed
        log_status = "completed" if merged_count > 0 else "failed or produced no output"

        logging.info(f"🏁 Scrape run {log_status}.")
        logging.info(f"   Duration: {datetime.timedelta(seconds=duration)}") # Nicer duration format
        logging.info(f"   Merged {merged_count} unique pages.")
        if final_output_file:
             logging.info(f"   Final output: {final_output_file}")
        else:
             logging.warning("   Final output file was not created.")


        # --- Call to send_email REMOVED ---
        # subject = f"{'✅' if count else '❌'} Tender Scrape Completed - {count} pages in {duration}s"
        # send_email(subject, LOG_FILE)

if __name__ == "__main__":
    # Kept user's version
    asyncio.run(scrape_all_pages())
