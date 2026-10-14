"""
main.py
Local web server for Handwritify. Run with:

    uvicorn main:app --port 8000

then open http://localhost:8000. Everything stays on this machine.

Each conversion is a "job" folder under jobs/<uuid>/:
    uploads/       the files as received (numbered to keep your order)
    images/        pictures found in the pages (img_1.png, ...)
    document.txt   the editable text (see markup.py)
    settings.json  the look/spacing settings last used
    previews/      the rendered handwriting pages (page_1.png, ...)
"""
import asyncio
import io
import json
import os
import re
import shutil
import sys
import time
import uuid
from contextlib import asynccontextmanager, suppress
from typing import Dict, List

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ValidationError
import pytesseract

from .export import markup_to_docx, pages_to_pdf
from .handwriting import PAPER_STYLES, font_family_name, list_fonts, render_pages
from .ingest import SUPPORTED_EXTENSIONS, Page, ingest_files
from .markup import image_ids
from .models import ImageItem, TextItem
from .schemas import RenderSettings


def _find_tesseract() -> str | None:
    configured = os.environ.get("TESSERACT_CMD")
    if configured:
        return configured

    candidates = []
    if os.name == "nt":
        candidates.extend([
            os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "Tesseract-OCR",
                "tesseract.exe",
            ),
            os.path.join(os.environ.get("ProgramFiles", ""), "Tesseract-OCR", "tesseract.exe"),
            os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Tesseract-OCR", "tesseract.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Tesseract-OCR", "tesseract.exe"),
            os.path.join(os.path.expanduser("~"), "Desktop", "clickme", "tesseract.exe"),
        ])
    elif sys.platform == "darwin":
        candidates.extend([
            "/opt/homebrew/bin/tesseract",
            "/usr/local/bin/tesseract",
        ])
    candidates.append("tesseract")

    for candidate in candidates:
        if not candidate:
            continue
        try:
            if os.path.isfile(candidate) or shutil.which(candidate):
                return candidate
        except OSError:
            continue
    return None


def _configure_tesseract() -> str | None:
    tesseract_cmd = _find_tesseract()
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    return tesseract_cmd


_configure_tesseract()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JOBS_DIR = os.path.join(BASE_DIR, "jobs")
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
JOB_RETENTION_SECONDS = 60 * 60
JOB_CLEANUP_INTERVAL_SECONDS = 60
os.makedirs(JOBS_DIR, exist_ok=True)


def _cleanup_expired_jobs(now: float = None):
    now = time.time() if now is None else now
    for name in os.listdir(JOBS_DIR):
        job_dir = os.path.join(JOBS_DIR, name)
        if not os.path.isdir(job_dir):
            continue
        try:
            with open(os.path.join(job_dir, "job_meta.json"), encoding="utf-8") as f:
                created_at = float(json.load(f)["created_at"])
        except (OSError, ValueError, KeyError, TypeError):
            try:
                created_at = os.path.getctime(job_dir)
            except OSError:
                continue
        if now - created_at >= JOB_RETENTION_SECONDS:
            shutil.rmtree(job_dir, ignore_errors=True)


async def _job_cleanup_loop():
    while True:
        await asyncio.to_thread(_cleanup_expired_jobs)
        await asyncio.sleep(JOB_CLEANUP_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(_app):
    cleanup_task = asyncio.create_task(_job_cleanup_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup_task


app = FastAPI(title="Handwritify", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

AUTH_USERNAME = os.environ.get("HANDWRITIFY_USERNAME")
AUTH_PASSWORD = os.environ.get("HANDWRITIFY_PASSWORD")


@app.get("/api/setup/status")
def setup_status():
    tesseract_cmd = _configure_tesseract()
    if os.name == "nt":
        platform_name = "Windows"
        download_url = "https://github.com/UB-Mannheim/tesseract/wiki"
        install_instructions = (
            "Tesseract OCR is included with the Handwritify Windows installer. "
            "If it is still missing, rerun the installer or download it here."
        )
    elif sys.platform == "darwin":
        platform_name = "macOS"
        download_url = "https://formulae.brew.sh/formula/tesseract"
        install_instructions = "Install with Homebrew using: brew install tesseract"
    else:
        platform_name = "Linux"
        download_url = "https://tesseract-ocr.github.io/tessdoc/Installation.html"
        install_instructions = "Install the tesseract-ocr package for your Linux distribution."
    return {
        "ready": bool(tesseract_cmd),
        "platform": platform_name,
        "download_url": download_url,
        "install_instructions": install_instructions,
    }


class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/api/auth/login")
def login(req: LoginRequest):
    if not AUTH_USERNAME or not AUTH_PASSWORD:
        raise HTTPException(
            status_code=503,
            detail=(
                "Login is not configured. Set HANDWRITIFY_USERNAME and "
                "HANDWRITIFY_PASSWORD before starting Handwritify."
            ),
        )
    if req.username != AUTH_USERNAME or req.password != AUTH_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    return {"authenticated": True, "message": "Welcome to Handwritify."}


# ------------------------------------------------------------- helpers
def _job_dir(job_id: str) -> str:
    try:
        uuid.UUID(job_id)  # also blocks path tricks like "../.."
    except ValueError:
        raise HTTPException(404, "Job not found")
    path = os.path.join(JOBS_DIR, job_id)
    if not os.path.isdir(path):
        raise HTTPException(404, "Job not found")
    return path


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _write(path: str, content: str):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _image_ids_on_disk(job_dir: str) -> List[str]:
    folder = os.path.join(job_dir, "images")
    if not os.path.isdir(folder):
        return []
    ids = [os.path.splitext(f)[0] for f in os.listdir(folder) if f.endswith(".png")]
    return sorted(ids, key=lambda i: int(re.sub(r"\D", "", i) or 0))


def _load_images(job_dir: str, ids) -> Dict[str, Image.Image]:
    out = {}
    for i in set(ids):
        p = os.path.join(job_dir, "images", f"{i}.png")
        if os.path.isfile(p):
            out[i] = Image.open(p).convert("RGB")
    return out


def _build_document(sources: List[tuple], images_dir: str):
    """Ordered items -> editable markup text, saving each picture to disk."""
    os.makedirs(images_dir, exist_ok=True)
    parts, n = [], 0
    for source_id, pages in sources:
        parts.append(f"[[STYLE:{source_id}]]")
        for page in pages:
            for item in page.items:
                if isinstance(item, TextItem):
                    if item.text.strip():
                        parts.append(item.text.strip())
                elif isinstance(item, ImageItem):
                    n += 1
                    img = item.image.copy()
                    img.thumbnail((1600, 1600))  # keep memory/disk sensible
                    img.save(os.path.join(images_dir, f"img_{n}.png"))
                    parts.append(f"[[IMG:img_{n}]]")
    return "\n\n".join(parts)


def _render_job(job_dir: str, text: str, s: RenderSettings,
                style_settings: Dict[str, RenderSettings] = None) -> int:
    images = _load_images(job_dir, image_ids(text))
    style_settings = style_settings or {}
    previews = os.path.join(job_dir, "previews")
    shutil.rmtree(previews, ignore_errors=True)
    os.makedirs(previews)
    page_count = 0

    def save_preview(img: Image.Image):
        nonlocal page_count
        page_count += 1
        img.save(os.path.join(previews, f"page_{page_count}.png"))

    render_pages(text, images, s, style_settings, page_sink=save_preview)
    _write(os.path.join(job_dir, "document.txt"), text)
    _write(os.path.join(job_dir, "settings.json"), s.model_dump_json())
    _write(os.path.join(job_dir, "file_settings.json"), json.dumps(
        {key: value.model_dump() for key, value in style_settings.items()}))
    return page_count


def _job_payload(job_id: str, job_dir: str, page_count: int) -> dict:
    v = int(time.time() * 1000)  # cache-buster so re-rendered pages refresh
    return {
        "job_id": job_id,
        "page_count": page_count,
        "previews": [f"/api/preview/{job_id}/{i}?v={v}" for i in range(1, page_count + 1)],
        "text": _read(os.path.join(job_dir, "document.txt")),
        "images": [{"id": i, "url": f"/api/image/{job_id}/{i}"} for i in _image_ids_on_disk(job_dir)],
    }


# ----------------------------------------------------------------- API
@app.get("/api/styles")
def get_styles():
    fonts = list_fonts()
    return {
        "fonts": fonts,
        "paper_styles": [{"key": p.key, "name": p.name} for p in PAPER_STYLES],
        "note": None if fonts else (
            "No handwriting fonts found in the fonts folder yet. Add some .ttf files "
            "and refresh this page. README.md lists free fonts."
        ),
    }


@app.post("/api/convert")
def convert(files: List[UploadFile] = File(...), settings: str = Form("{}"),
            file_settings: str = Form("{}")):
    try:
        s = RenderSettings.model_validate_json(settings)
        input_file_settings = json.loads(file_settings)
        if not isinstance(input_file_settings, dict):
            raise ValueError("file_settings must be an object")
        per_file = {key: RenderSettings.model_validate(value)
                for key, value in input_file_settings.items()}
    except ValidationError as e:
        raise HTTPException(422, f"Invalid settings: {e.errors()[0]['loc']} {e.errors()[0]['msg']}")
    except (ValueError, json.JSONDecodeError) as e:
        raise HTTPException(422, f"Invalid file settings: {e}")

    job_id = str(uuid.uuid4())
    job_dir = os.path.join(JOBS_DIR, job_id)
    upload_dir = os.path.join(job_dir, "uploads")
    os.makedirs(upload_dir)

    saved = []
    for idx, f in enumerate(files, start=1):
        base = re.sub(r"[^\w.\- ]", "_", os.path.basename(f.filename or "file"))
        if os.path.splitext(base)[1].lower() not in SUPPORTED_EXTENSIONS:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise HTTPException(400, f"Unsupported file type: {base}. Use PDF, PPTX, JPG or PNG.")
        dest = os.path.join(upload_dir, f"{idx:03d}_{base}")  # prefix keeps upload order, avoids name clashes
        with open(dest, "wb") as out:
            shutil.copyfileobj(f.file, out)
        saved.append(dest)

    with open(os.path.join(job_dir, "job_meta.json"), "w", encoding="utf-8") as f:
        json.dump({"created_at": time.time()}, f)

    try:
        sources = [(f"file_{idx}", ingest_files([path]))
               for idx, path in enumerate(saved, start=1)]
        text = _build_document(sources, os.path.join(job_dir, "images"))
    except Exception as e:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(500, f"Could not read the files: {e}")
    if not text.strip():
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(422, "No readable text or pictures were found in the uploaded files.")

    count = _render_job(job_dir, text, s, per_file)
    return _job_payload(job_id, job_dir, count)


class RerenderRequest(BaseModel):
    text: str
    settings: RenderSettings
    file_settings: Dict[str, RenderSettings] | None = None


@app.post("/api/rerender/{job_id}")
def rerender(job_id: str, req: RerenderRequest):
    job_dir = _job_dir(job_id)
    if not req.text.strip():
        raise HTTPException(422, "The text is empty - add some text before re-rendering.")
    count = _render_job(job_dir, req.text, req.settings, req.file_settings or {})
    return _job_payload(job_id, job_dir, count)


@app.get("/api/preview/{job_id}/{page_num}")
def preview(job_id: str, page_num: int):
    path = os.path.join(_job_dir(job_id), "previews", f"page_{page_num}.png")
    if not os.path.isfile(path):
        raise HTTPException(404, "Page not found")
    return FileResponse(path, media_type="image/png")


@app.get("/api/image/{job_id}/{image_id}")
def picture(job_id: str, image_id: str):
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", image_id):
        raise HTTPException(404, "Image not found")
    path = os.path.join(_job_dir(job_id), "images", f"{image_id}.png")
    if not os.path.isfile(path):
        raise HTTPException(404, "Image not found")
    return FileResponse(path, media_type="image/png")


@app.post("/api/image/{job_id}")
def add_pasted_image(job_id: str, file: UploadFile = File(...)):
    job_dir = _job_dir(job_id)
    data = file.file.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "Pasted images must be 10 MB or smaller.")
    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.width * source.height > 40_000_000:
                raise HTTPException(413, "Pasted image dimensions are too large.")
            image = ImageOps.exif_transpose(source).convert("RGBA")
        background = Image.new("RGBA", image.size, "white")
        background.alpha_composite(image)
        image = background.convert("RGB")
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError):
        raise HTTPException(415, "The pasted data is not a supported image.")

    image.thumbnail((1600, 1600))
    image_id = f"pasted_{uuid.uuid4().hex}"
    image.save(os.path.join(job_dir, "images", f"{image_id}.png"))
    return {"id": image_id, "url": f"/api/image/{job_id}/{image_id}"}


@app.get("/api/download/{job_id}")
def download(job_id: str, fmt: str = "pdf"):
    job_dir = _job_dir(job_id)
    s = RenderSettings.model_validate_json(_read(os.path.join(job_dir, "settings.json")))

    if fmt == "pdf":
        folder = os.path.join(job_dir, "previews")
        names = sorted(os.listdir(folder), key=lambda n: int(re.sub(r"\D", "", n)))
        out = os.path.join(job_dir, "handwritten.pdf")
        pages_to_pdf([Image.open(os.path.join(folder, n)) for n in names], out)
        return FileResponse(out, filename="handwritten.pdf", media_type="application/pdf")

    if fmt == "docx":
        text = _read(os.path.join(job_dir, "document.txt"))
        out = os.path.join(job_dir, "converted.docx")
        markup_to_docx(text, _load_images(job_dir, image_ids(text)), s, out, font_family_name(s.style))
        return FileResponse(
            out, filename="converted.docx",
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

    raise HTTPException(400, "fmt must be 'pdf' or 'docx'")


# Serve the frontend last so /api/* routes above take priority
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
