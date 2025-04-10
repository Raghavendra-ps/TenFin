from fastapi import FastAPI, Request, Form
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
import os
from filter_engine import run_filter

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

@app.get("/view/{subdir}", response_class=HTMLResponse)
async def view_tenders(request: Request, subdir: str):
    file_path = os.path.join(FILTERED_PATH, subdir, "Filtered_Tenders.txt")
    if not os.path.exists(file_path):
        return templates.TemplateResponse("error.html", {"request": request, "error": "File not found"})

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    return templates.TemplateResponse("view.html", {
        "request": request,
        "subdir": subdir,
        "content": content
    })

@app.get("/download/{subdir}")
async def download_tender_file(subdir: str):
    file_path = os.path.join(FILTERED_PATH, subdir, "Filtered_Tenders.txt")
    if not os.path.exists(file_path):
        return {"error": "File not found"}
    return FileResponse(file_path, filename=f"{subdir}_Filtered_Tenders.txt", media_type='text/plain')

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
