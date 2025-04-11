from fastapi import FastAPI, Request, Form
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import os
import re
from filter_engine import run_filter
from openpyxl import Workbook
from tempfile import NamedTemporaryFile

# === CONFIG ===
BASE_PATH = "/mnt/dietpi_userdata/nextcloud_data/__groupfolders/7"
FILTERED_PATH = os.path.join(BASE_PATH, "Filtered Tenders")

app = FastAPI()
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def homepage(request: Request):
    subdirs = [
        name for name in os.listdir(FILTERED_PATH)
        if os.path.isdir(os.path.join(FILTERED_PATH, name))
    ]
    return templates.TemplateResponse("index.html", {"request": request, "subdirs": subdirs})


TENDER_BLOCK_PATTERN = re.compile(r"^\d+\.\s*$")

def parse_tenders_from_file(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
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

    tenders = []
    for block in blocks:
        tender = {
            "start_date": "",
            "end_date": "",
            "opening_date": "",
            "title": "",
            "tender_id": "",
            "department": ""
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

        # Optional debug
        # print(tender)

        tenders.append(tender)

    return tenders


@app.get("/view/{subdir}", response_class=HTMLResponse)
async def view_tenders(request: Request, subdir: str):
    file_path = os.path.join(FILTERED_PATH, subdir, "Filtered_Tenders.txt")
    if not os.path.exists(file_path):
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": "File not found"
        })

    tenders = parse_tenders_from_file(file_path)

    return templates.TemplateResponse("view.html", {
        "request": request,
        "subdir": subdir,
        "tenders": tenders
    })


@app.get("/download/{subdir}")
async def download_tender_file(subdir: str):
    file_path = os.path.join(FILTERED_PATH, subdir, "Filtered_Tenders.txt")
    if not os.path.exists(file_path):
        return {"error": "File not found"}

    tenders = parse_tenders_from_file(file_path)

    wb = Workbook()
    ws = wb.active
    ws.title = "Tenders"
    ws.append(["Start Date", "End Date", "Opening Date", "Title", "Tender ID", "Department"])

    for tender in tenders:
        ws.append([
            tender["start_date"],
            tender["end_date"],
            tender["opening_date"],
            tender["title"],
            tender["tender_id"],
            tender["department"]
        ])

    with NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        wb.save(tmp.name)
        return FileResponse(
            tmp.name,
            filename=f"{subdir}_Filtered_Tenders.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )


@app.get("/run-filter", response_class=HTMLResponse)
async def run_filter_form(request: Request):
    tender_files = sorted([
        f for f in os.listdir(BASE_PATH)
        if f.startswith("Final_Tender_List") and f.endswith(".txt")
    ])
    return templates.TemplateResponse("run_filter.html", {
        "request": request,
        "tender_files": tender_files
    })


@app.post("/run-filter", response_class=HTMLResponse)
async def run_filter_submit(
    request: Request,
    keywords: str = Form(...),
    regex: bool = Form(False),
    filter_name: str = Form(...),
    file: str = Form(...)
):
    try:
        keyword_list = [kw.strip() for kw in keywords.split(",") if kw.strip()]
        result_path = run_filter(
            base_folder=BASE_PATH,
            tender_filename=file,
            keywords=keyword_list,
            use_regex=regex,
            filter_name=filter_name
        )
        subdir = f"{filter_name} Tenders"
        return templates.TemplateResponse("success.html", {
            "request": request,
            "subdir": subdir,
            "result_path": result_path
        })
    except Exception as e:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": str(e)
        })


@app.get("/delete/{subdir}")
async def delete_tender_set(subdir: str):
    folder = os.path.join(FILTERED_PATH, subdir)
    if os.path.isdir(folder):
        for f in os.listdir(folder):
            os.remove(os.path.join(folder, f))
        os.rmdir(folder)
    return RedirectResponse(url="/", status_code=302)
