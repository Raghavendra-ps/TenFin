import asyncio
import os
import datetime
import logging
import re
import subprocess
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
import os
import logging
import datetime

# === CONFIG ===
SAVE_DIR = "/root/TenFin/scraped_data/Filtered Tenders"
BASE_URL = "https://eprocure.gov.in/eprocure/app?component=%24TablePages.linkPage&page=FrontEndAdvancedSearchResult&service=direct&session=T&sp=AFrontEndAdvancedSearchResult%2Ctable&sp={}"
MAX_PAGES = 150
RETRY_LIMIT = 3
CONCURRENCY = 10
EMAIL = "raghavendra_ps@icloud.com"

# === LOG CONFIG ===
LOG_DIR = "/var/log/GWS_Logs"
LOG_FILE = os.path.join(LOG_DIR, "log.txt")
TODAY = datetime.datetime.now().strftime("%Y-%m-%d")

# Create directory if it doesn't exist
os.makedirs(LOG_DIR, exist_ok=True)

# Check if today's header is already in the log file
def ensure_date_header():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            if f"======== {TODAY} ========" in f.read():
                return
    with open(LOG_FILE, "a") as f:
        f.write(f"\n\n======== {TODAY} ========\n")

ensure_date_header()

# Setup logging to append to the static file
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)

# === UNWANTED TEXT TO REMOVE ===
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

def natural_sort_key(filename):
    match = re.search(r"(\d+)", filename)
    return int(match.group(1)) if match else float("inf")

async def fetch_single_page(page, page_number):
    url = BASE_URL.format(page_number)
    for attempt in range(1, RETRY_LIMIT + 1):
        try:
            logging.info(f"📄 Fetching Page {page_number} (Attempt {attempt})")
            await page.goto("https://eprocure.gov.in/eprocure/app", wait_until="networkidle")
            await page.goto(url, wait_until="networkidle", timeout=10000)
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

async def fetch_pages_concurrently(playwright):
    browser = await playwright.chromium.launch(headless=True)
    pages = await asyncio.gather(*[browser.new_page() for _ in range(CONCURRENCY)])
    all_results = {}
    last_content = None
    stop = False
    current = 1

    while current <= MAX_PAGES and not stop:
        batch = []
        for i in range(CONCURRENCY):
            if current > MAX_PAGES:
                break
            batch.append(fetch_single_page(pages[i], current))
            current += 1

        results = await asyncio.gather(*batch)
        for page_number, content in results:
            if not content or content == last_content or "No Records Found" in content or len(content.strip()) < 50:
                logging.info(f"🛑 Stopping at Page {page_number}: Duplicate or empty.")
                stop = True
                break

            save_path = os.path.join(SAVE_DIR, f"Page {page_number}.txt")
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(content)
            all_results[page_number] = content
            last_content = content

    await browser.close()
    return all_results

async def merge_and_cleanup():
    today = datetime.datetime.now().strftime("%d-%m-%Y")
    final_path = os.path.join(SAVE_DIR, f"Final_Tender_List {today}.txt")
    page_files = sorted([f for f in os.listdir(SAVE_DIR) if f.startswith("Page ") and f.endswith(".txt")], key=natural_sort_key)
    seen = set()
    count = 0

    with open(final_path, "w", encoding="utf-8") as out:
        for fname in page_files:
            path = os.path.join(SAVE_DIR, fname)
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
                if content not in seen:
                    out.write(content + "\n\n")
                    seen.add(content)
                    count += 1
                else:
                    logging.info(f"🗑️ Duplicate skipped: {fname}")
            os.remove(path)

    os.system('cd /var/www/nextcloud && sudo -u www-data php occ files:scan --path="CEO/files/Artificial Intelligence"')
    logging.info(f"✅ Merged {count} pages to: {final_path}")
    return count, final_path

def send_email(subject, log_file_path):
    try:
        with open(log_file_path, "r") as log_file:
            log_content = log_file.read()

        message = f"""Subject: {subject}
To: {EMAIL}

{log_content}
"""

        process = subprocess.Popen(
            ['msmtp', EMAIL],
            stdin=subprocess.PIPE
        )
        process.communicate(input=message.encode('utf-8'))
        logging.info("📧 Email sent via msmtp.")

    except Exception as e:
        logging.error(f"❌ Failed to send email via msmtp: {e}")

async def scrape_all_pages():
    start_time = datetime.datetime.now()
    async with async_playwright() as p:
        logging.info("🚀 Starting concurrent scrape")
        results = await fetch_pages_concurrently(p)

    count, output_path = await merge_and_cleanup()
    end_time = datetime.datetime.now()
    duration = (end_time - start_time).seconds

    subject = f"{'✅' if count else '❌'} Tender Scrape Completed - {count} pages in {duration}s"
    send_email(subject, LOG_FILE)

if __name__ == "__main__":
    asyncio.run(scrape_all_pages())
