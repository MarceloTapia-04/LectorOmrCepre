from __future__ import annotations

import csv
import io
import json
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
import cv2
import pymupdf
import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.grid import CANVAS_H, CANVAS_W, OPTIONS, center, detect_grid

import os
import sys
from concurrent.futures import ThreadPoolExecutor

# ── Rutas compatibles con PyInstaller onefile ──────────────────────────────
if getattr(sys, "frozen", False):
    # Cuando corre como .exe:
    #   sys._MEIPASS  → carpeta temporal con el código/assets del bundle
    #   sys.executable → ruta del propio .exe
    BUNDLE_ROOT = Path(sys._MEIPASS)           # type: ignore[attr-defined]
    DATA_ROOT   = Path(sys.executable).parent  # carpeta junto al .exe
else:
    BUNDLE_ROOT = Path(__file__).resolve().parent.parent
    DATA_ROOT   = BUNDLE_ROOT

# ROOT se usa para localizar app/static (dentro del bundle)
ROOT = BUNDLE_ROOT
# DATA, UPLOADS y PROCESSED van junto al .exe (persistentes entre ejecuciones)
DATA      = DATA_ROOT / "data"
UPLOADS   = DATA / "uploads"
PROCESSED = DATA / "processed"
for directory in (UPLOADS, PROCESSED):
    directory.mkdir(parents=True, exist_ok=True)

MAX_SHEETS = 2000
_WORKERS = min(8, max(4, os.cpu_count() or 4))


@dataclass
class Answer:
    question: int
    answer: str = ""
    state: str = "blank"
    confidence: float = 0.0
    scores: dict[str, float] = field(default_factory=dict)


@dataclass
class Sheet:
    id: str
    source_name: str
    page_number: int | None
    source_path: Path
    corrected_path: Path | None = None
    status: str = "pending"
    threshold: int = 180
    student_code: str = ""
    student_name: str = ""
    score: float = 0.0
    correct_count: int = 0
    incorrect_count: int = 0
    blank_count: int = 0
    answers: list[Answer] = field(default_factory=list)
    grid_calibration: list[dict[str, float]] | None = None


@dataclass
class Batch:
    id: str
    sheets: list[Sheet] = field(default_factory=list)


BATCHES: dict[str, Batch] = {}
app = FastAPI(title="Lector OMR local")


class ReadRequest(BaseModel):
    threshold: int = Field(default=180, ge=0, le=255)


class AnswerUpdateItem(BaseModel):
    question: int
    answer: str = ""
    state: str = "blank"
    confidence: float = 1.0


class AnswersUpdateRequest(BaseModel):
    answers: list[AnswerUpdateItem]


class StudentItem(BaseModel):
    code: str = ""
    name: str = ""


class AssignStudentRequest(BaseModel):
    code: str = ""
    name: str = ""
    student: str = ""


class StudentsUpdateRequest(BaseModel):
    students_text: str | None = None
    students: list[StudentItem] | None = None


class AnswerKeyRequest(BaseModel):
    key: dict[int, str] | None = None
    key_text: str | None = None


STUDENTS_FILE = DATA / "alumnos.txt"
KEY_FILE = DATA / "clave.json"


def load_students_from_file() -> list[dict[str, str]]:
    if not STUDENTS_FILE.exists():
        return []
    students = []
    seen = set()
    with STUDENTS_FILE.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            clean = line.strip()
            if not clean or clean.startswith("#"):
                continue
            code = ""
            name = ""
            if " - " in clean:
                parts = clean.split(" - ", 1)
                code, name = parts[0].strip(), parts[1].strip()
            elif "," in clean:
                parts = clean.split(",", 1)
                code, name = parts[0].strip(), parts[1].strip()
            elif "\t" in clean:
                parts = clean.split("\t", 1)
                code, name = parts[0].strip(), parts[1].strip()
            elif ";" in clean:
                parts = clean.split(";", 1)
                code, name = parts[0].strip(), parts[1].strip()
            else:
                parts = clean.split(" ", 1)
                if len(parts) == 2 and parts[0].isalnum() and len(parts[0]) >= 3:
                    code, name = parts[0].strip(), parts[1].strip()
                else:
                    name = clean
            label = f"{code} - {name}" if code and name else (code or name)
            key = (code.upper(), name.upper())
            if key not in seen:
                seen.add(key)
                students.append({"code": code, "name": name, "label": label})
    return students


def load_answer_key() -> dict[int, str]:
    if not KEY_FILE.exists():
        return {}
    try:
        with KEY_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
            return {int(k): str(v).upper().strip() for k, v in data.items() if str(v).strip()}
    except Exception:
        return {}


def save_answer_key(key_dict: dict[int, str]) -> None:
    cleaned = {str(k): str(v).upper().strip() for k, v in key_dict.items() if str(v).strip()}
    with KEY_FILE.open("w", encoding="utf-8") as f:
        json.dump(cleaned, f, indent=2, ensure_ascii=False)


def parse_key_text(text: str) -> dict[int, str]:
    res: dict[int, str] = {}
    tokens = text.replace(",", " ").replace(";", " ").replace("\t", " ").split()
    idx = 1
    for token in tokens:
        token = token.strip().upper()
        if not token:
            continue
        matched = False
        for sep in (":", "-", "."):
            if sep in token:
                parts = token.split(sep, 1)
                if parts[0].isdigit():
                    q_num = int(parts[0])
                    ans = parts[1].strip()
                    if ans in "ABCDE":
                        res[q_num] = ans
                        matched = True
                break
        if not matched:
            if token in "ABCDE":
                if idx <= 140:
                    res[idx] = token
                    idx += 1
            elif token.isalpha() and all(c in "ABCDE" for c in token):
                for c in token:
                    if idx <= 140:
                        res[idx] = c
                        idx += 1
    return res


def grade_sheet(sheet: Sheet, key: dict[int, str] | None = None) -> None:
    if key is None:
        key = load_answer_key()
    if not key:
        sheet.score = 0.0
        sheet.correct_count = 0
        sheet.incorrect_count = 0
        sheet.blank_count = len([a for a in sheet.answers if not a.answer or a.state == "blank"])
        return

    correct = 0
    incorrect = 0
    blank = 0
    points = 0.0

    for ans in sheet.answers:
        q = ans.question
        correct_ans = key.get(q, "").strip().upper()
        user_ans = (ans.answer or "").strip().upper()

        if not correct_ans:
            if not user_ans or ans.state == "blank":
                blank += 1
            continue

        if not user_ans or ans.state == "blank":
            blank += 1
            # 0 puntos por respuesta en blanco
        elif ans.state in ("ok", "manual") and user_ans == correct_ans:
            correct += 1
            points += 1.0
        else:
            # Respuesta incorrecta o doble marca: -0.01 puntos
            incorrect += 1
            points -= 0.01

    sheet.correct_count = correct
    sheet.incorrect_count = incorrect
    sheet.blank_count = blank
    sheet.score = round(points, 4)


def sheet_payload(sheet: Sheet, with_answers: bool = False) -> dict:
    counts = {key: 0 for key in ("ok", "blank", "multiple", "uncertain", "manual")}
    for answer in sheet.answers:
        counts[answer.state] = counts.get(answer.state, 0) + 1
    counts["marked"] = counts["ok"] + counts["manual"]
    student_label = f"{sheet.student_code} - {sheet.student_name}".strip(" - ") if (sheet.student_code or sheet.student_name) else ""
    payload = {
        "id": sheet.id,
        "source_name": sheet.source_name,
        "page_number": sheet.page_number,
        "student_code": sheet.student_code,
        "student_name": sheet.student_name,
        "student": student_label,
        "status": sheet.status,
        "threshold": sheet.threshold,
        "score": sheet.score,
        "correct_count": sheet.correct_count,
        "incorrect_count": sheet.incorrect_count,
        "blank_count": sheet.blank_count,
        "counts": counts,
        "grid_calibration": sheet.grid_calibration,
        "image_url": f"/api/sheets/{sheet.id}/image" if sheet.corrected_path else None,
        "source_image_url": f"/api/sheets/{sheet.id}/source-image",
    }
    if with_answers:
        payload["answers"] = [asdict(answer) for answer in sheet.answers]
    return payload


def find_batch_and_sheet(sheet_id: str) -> tuple[Batch, Sheet]:
    for batch in BATCHES.values():
        for sheet in batch.sheets:
            if sheet.id == sheet_id:
                return batch, sheet
    raise HTTPException(404, "Hoja no encontrada")


def find_sheet(sheet_id: str) -> Sheet:
    _, sheet = find_batch_and_sheet(sheet_id)
    return sheet


def page_images(file_path: Path, content_type: str) -> list[np.ndarray]:
    if content_type == "application/pdf" or file_path.suffix.lower() == ".pdf":
        pages = []
        with pymupdf.open(file_path) as document:
            for page in document:
                pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
                arr = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, pixmap.n)
                image = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR) if pixmap.n == 3 else arr
                pages.append(image)
        return pages
    image = cv2.imread(str(file_path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("No se pudo leer la imagen")
    return [image]


def order_corners(points: np.ndarray) -> np.ndarray:
    ordered = np.zeros((4, 2), dtype=np.float32)
    sums = points.sum(axis=1)
    differences = np.diff(points, axis=1).reshape(-1)
    ordered[0] = points[np.argmin(sums)]
    ordered[2] = points[np.argmax(sums)]
    ordered[1] = points[np.argmin(differences)]
    ordered[3] = points[np.argmax(differences)]
    return ordered


def normalize_image(image: np.ndarray) -> np.ndarray:
    # Match the original HTML canvas model exactly: the complete image is
    # drawn into a fixed 1280 x 920 workspace before its grid is calibrated.
    return cv2.resize(image, (CANVAS_W, CANVAS_H), interpolation=cv2.INTER_LINEAR)


def calibrated_center(block: int, row: int, option: int, calibration: list[dict[str, float]] | None) -> tuple[float, float]:
    x, y = center(block, row, option)
    if not calibration:
        return x, y
    # Four corner bubbles per block allow a bilinear interpolation that keeps
    # the grid aligned even when the scan has local skew or perspective.
    top_left, top_right, bottom_left, bottom_right = calibration[block * 4:block * 4 + 4]
    horizontal = option / 4
    vertical = row / 34
    top_x = top_left["x"] + horizontal * (top_right["x"] - top_left["x"])
    top_y = top_left["y"] + horizontal * (top_right["y"] - top_left["y"])
    bottom_x = bottom_left["x"] + horizontal * (bottom_right["x"] - bottom_left["x"])
    bottom_y = bottom_left["y"] + horizontal * (bottom_right["y"] - bottom_left["y"])
    return (
        top_x + vertical * (bottom_x - top_x),
        top_y + vertical * (bottom_y - top_y),
    )


_RADIUS = 6.2
_R_INT = int(np.ceil(_RADIUS))
_YY, _XX = np.ogrid[-_R_INT:_R_INT+1, -_R_INT:_R_INT+1]
_CIRCLE_MASK = (_XX**2 + _YY**2) <= _RADIUS**2


def mean_ink(inv_gray: np.ndarray, cx: float, cy: float) -> float:
    """Cálculo vectorizado ultra rápido de tinta invertida sobre el parche circular."""
    x0, y0 = int(round(cx)), int(round(cy))
    y_min, y_max = max(0, y0 - _R_INT), min(CANVAS_H, y0 + _R_INT + 1)
    x_min, x_max = max(0, x0 - _R_INT), min(CANVAS_W, x0 + _R_INT + 1)
    patch = inv_gray[y_min:y_max, x_min:x_max]
    mask = _CIRCLE_MASK[y_min - (y0 - _R_INT):y_max - (y0 - _R_INT), x_min - (x0 - _R_INT):x_max - (x0 - _R_INT)]
    return float(patch[mask].mean()) if mask.any() else 0.0


def read_omr(image: np.ndarray, calibration: list[dict[str, float]] | None = None, threshold: int = 180) -> list[Answer]:
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image
    inv_gray = 255 - gray

    answers: list[Answer] = []
    for block in range(4):
        for row in range(35):
            question = block * 35 + row + 1
            scores = [mean_ink(inv_gray, *calibrated_center(block, row, option, calibration)) for option in range(5)]
            ranking = sorted(range(5), key=lambda index: scores[index], reverse=True)
            best, second = ranking[:2]
            contrast = scores[best] - scores[second]
            confidence = max(0.0, min(1.0, (scores[best] - threshold + contrast) / 100))
            marked_indices = [i for i in range(5) if scores[i] >= threshold]
            if len(marked_indices) >= 2 or (scores[best] >= threshold and scores[second] >= threshold - 8 and contrast < 20):
                marked_opts = sorted(set(marked_indices + [best, second])) if scores[second] >= threshold - 8 else sorted(marked_indices)
                value, state = "".join(OPTIONS[i] for i in marked_opts), "multiple"
            elif len(marked_indices) == 1 and contrast >= 20:
                value, state = OPTIONS[marked_indices[0]], "ok"
            elif scores[best] >= threshold:
                value, state = OPTIONS[best], "uncertain"
            else:
                value, state = "", "blank"
            answers.append(Answer(question, value, state, round(confidence, 2), dict(zip(OPTIONS, map(lambda n: round(n, 1), scores)))))
    return answers


def process_sheet(sheet: Sheet) -> None:
    source = cv2.imread(str(sheet.source_path), cv2.IMREAD_COLOR)
    if source is None:
        raise ValueError("No se pudo abrir la hoja")
    corrected = normalize_image(source)
    destination = PROCESSED / f"{sheet.id}.jpg"
    cv2.imwrite(str(destination), corrected)
    sheet.corrected_path = destination
    if not sheet.grid_calibration:
        sheet.grid_calibration = detect_grid(corrected)
    sheet.answers = read_omr(corrected, sheet.grid_calibration, sheet.threshold)
    grade_sheet(sheet)
    sheet.status = "review"


def _save_and_unpack_upload(upload: UploadFile) -> list[tuple[str, str, int | None, Path]]:
    suffix = Path(upload.filename or "archivo").suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".pdf"}:
        raise HTTPException(400, f"Formato no admitido: {upload.filename}")
    saved = UPLOADS / f"{uuid.uuid4().hex}{suffix}"
    with saved.open("wb") as target:
        shutil.copyfileobj(upload.file, target)
    pages = page_images(saved, upload.content_type or "")
    results = []
    for page_number, page in enumerate(pages, 1):
        sheet_id = uuid.uuid4().hex
        page_path = UPLOADS / f"{sheet_id}.jpg"
        cv2.imwrite(str(page_path), page)
        results.append((sheet_id, upload.filename or "sin-nombre", page_number if len(pages) > 1 else None, page_path))
    return results


@app.post("/api/batches")
async def create_batch(files: list[UploadFile] = File(...)):
    if not files:
        raise HTTPException(400, "Seleccione al menos un archivo")
    batch = Batch(uuid.uuid4().hex)
    BATCHES[batch.id] = batch
    try:
        new_sheets: list[Sheet] = []
        with ThreadPoolExecutor(max_workers=_WORKERS) as executor:
            file_results = list(executor.map(_save_and_unpack_upload, files))

        for unpacked in file_results:
            if len(batch.sheets) + len(new_sheets) + len(unpacked) > MAX_SHEETS:
                raise HTTPException(400, f"El lote supera el límite de {MAX_SHEETS} hojas")
            for sheet_id, source_name, page_num, page_path in unpacked:
                new_sheets.append(Sheet(sheet_id, source_name, page_num, page_path))

        batch.sheets.extend(new_sheets)

        # Procesar análisis OMR en paralelo aprovechando todos los núcleos de CPU
        with ThreadPoolExecutor(max_workers=_WORKERS) as executor:
            list(executor.map(process_sheet, new_sheets))

    except Exception:
        BATCHES.pop(batch.id, None)
        raise
    return {"id": batch.id, "sheets": [sheet_payload(sheet) for sheet in batch.sheets]}


@app.post("/api/batches/{batch_id}/sheets")
async def add_sheets_to_batch(batch_id: str, files: list[UploadFile] = File(...)):
    batch = BATCHES.get(batch_id)
    if not batch:
        raise HTTPException(404, "Lote no encontrado")
    if not files:
        raise HTTPException(400, "Seleccione al menos un archivo")
    new_sheets: list[Sheet] = []
    with ThreadPoolExecutor(max_workers=_WORKERS) as executor:
        file_results = list(executor.map(_save_and_unpack_upload, files))

    for unpacked in file_results:
        if len(batch.sheets) + len(new_sheets) + len(unpacked) > MAX_SHEETS:
            raise HTTPException(400, f"El lote supera el límite de {MAX_SHEETS} hojas")
        for sheet_id, source_name, page_num, page_path in unpacked:
            new_sheets.append(Sheet(sheet_id, source_name, page_num, page_path))

    with ThreadPoolExecutor(max_workers=_WORKERS) as executor:
        list(executor.map(process_sheet, new_sheets))

    batch.sheets.extend(new_sheets)
    return {"id": batch.id, "sheets": [sheet_payload(sheet) for sheet in batch.sheets], "added": len(new_sheets)}


@app.get("/api/batches/{batch_id}")
def get_batch(batch_id: str):
    batch = BATCHES.get(batch_id)
    if not batch:
        raise HTTPException(404, "Lote no encontrado")
    return {"id": batch.id, "sheets": [sheet_payload(sheet) for sheet in batch.sheets]}


@app.get("/api/sheets/{sheet_id}")
def get_sheet(sheet_id: str):
    return sheet_payload(find_sheet(sheet_id), with_answers=True)


@app.get("/api/sheets/{sheet_id}/image")
def get_image(sheet_id: str):
    sheet = find_sheet(sheet_id)
    if not sheet.corrected_path:
        raise HTTPException(404, "Imagen no procesada")
    return FileResponse(sheet.corrected_path, media_type="image/jpeg")


@app.get("/api/sheets/{sheet_id}/source-image")
def get_source_image(sheet_id: str):
    return FileResponse(find_sheet(sheet_id).source_path, media_type="image/jpeg")


@app.post("/api/sheets/{sheet_id}/read")
def reread_sheet(sheet_id: str, request: ReadRequest):
    sheet = find_sheet(sheet_id)
    if not sheet.corrected_path:
        raise HTTPException(400, "La hoja no ha sido procesada")
    corrected = cv2.imread(str(sheet.corrected_path), cv2.IMREAD_COLOR)
    sheet.threshold = request.threshold
    sheet.answers = read_omr(corrected, sheet.grid_calibration, sheet.threshold)
    grade_sheet(sheet)
    sheet.status = "review"
    return sheet_payload(sheet, with_answers=True)


@app.post("/api/sheets/{sheet_id}/answers")
def update_answers(sheet_id: str, request: AnswersUpdateRequest):
    sheet = find_sheet(sheet_id)
    if len(request.answers) != 140:
        raise HTTPException(400, "Se requieren exactamente 140 respuestas")
    scores_map = {ans.question: ans.scores for ans in sheet.answers}
    old_answers_map = {ans.question: ans.answer for ans in sheet.answers}
    new_answers: list[Answer] = []
    for item in request.answers:
        val = item.answer.strip().upper() if item.answer else ""
        old_val = old_answers_map.get(item.question, "")
        if val in ("MULTIPLE", "DOBLE") or len(val) > 1 or item.state == "multiple":
            state = "multiple"
            val = val if (val in ("MULTIPLE", "DOBLE") or len(val) > 1) else "DOBLE"
            confidence = 1.0
        elif not val:
            state = "blank"
            confidence = 1.0 if val != old_val else item.confidence
        elif val != old_val or item.state == "manual":
            state = "manual"
            confidence = 1.0
        else:
            state = item.state if val else "blank"
            confidence = item.confidence
        new_answers.append(
            Answer(
                question=item.question,
                answer=val,
                state=state,
                confidence=confidence,
                scores=scores_map.get(item.question, {}),
            )
        )
    sheet.answers = new_answers
    grade_sheet(sheet)
    sheet.status = "review"
    return sheet_payload(sheet, with_answers=True)


@app.post("/api/sheets/{sheet_id}/approve")
def approve_sheet(sheet_id: str):
    sheet = find_sheet(sheet_id)
    if not ((sheet.student_code or "").strip() or (sheet.student_name or "").strip()):
        raise HTTPException(400, "No se puede aprobar la hoja porque no tiene un estudiante asignado")
    if len(sheet.answers) != 140:
        raise HTTPException(400, "La hoja no tiene una lectura completa")
    grade_sheet(sheet)
    sheet.status = "approved"
    return sheet_payload(sheet, with_answers=True)


@app.get("/api/answer-key")
def get_answer_key():
    key = load_answer_key()
    return {"key": key, "count": len(key)}


@app.post("/api/answer-key")
def set_answer_key(request: AnswerKeyRequest):
    key_dict: dict[int, str] = {}
    if request.key is not None:
        key_dict = {int(k): str(v).upper().strip() for k, v in request.key.items() if str(v).strip()}
    elif request.key_text is not None:
        key_dict = parse_key_text(request.key_text)

    save_answer_key(key_dict)

    # Recalcular todos los exámenes y ponerlos en "review"
    for batch in BATCHES.values():
        for sheet in batch.sheets:
            sheet.status = "review"
            grade_sheet(sheet, key_dict)

    return {"key": key_dict, "count": len(key_dict), "message": "Clave guardada y exámenes puestos en revisión."}


@app.get("/api/students")
def get_students():
    return {"students": load_students_from_file()}


@app.post("/api/students")
def update_students(request: StudentsUpdateRequest):
    if request.students_text is not None:
        lines = [line.strip() for line in request.students_text.splitlines() if line.strip()]
        with STUDENTS_FILE.open("w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    elif request.students is not None:
        lines = [f"{s.code} - {s.name}".strip(" - ") for s in request.students if s.code or s.name]
        with STUDENTS_FILE.open("w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return {"students": load_students_from_file()}


@app.post("/api/sheets/{sheet_id}/student")
def assign_student(sheet_id: str, request: AssignStudentRequest):
    batch, sheet = find_batch_and_sheet(sheet_id)
    code = request.code.strip()
    name = request.name.strip()
    student_str = request.student.strip()

    if not code and not name and student_str:
        if " - " in student_str:
            parts = student_str.split(" - ", 1)
            code, name = parts[0].strip(), parts[1].strip()
        elif "," in student_str:
            parts = student_str.split(",", 1)
            code, name = parts[0].strip(), parts[1].strip()
        else:
            parts = student_str.split(" ", 1)
            if len(parts) == 2 and parts[0].isalnum() and len(parts[0]) >= 3:
                code, name = parts[0].strip(), parts[1].strip()
            else:
                name = student_str

    # Validar que ningún otro examen en este lote tenga ya asignado este estudiante
    if code or name:
        target_code = code.lower() if code else ""
        target_name = name.lower() if name else ""
        for idx, other in enumerate(batch.sheets, 1):
            if other.id != sheet.id:
                other_code = (other.student_code or "").strip().lower()
                other_name = (other.student_name or "").strip().lower()

                if target_code and other_code and target_code == other_code:
                    other_display = f"{other.student_code} - {other.student_name}".strip(" - ")
                    raise HTTPException(
                        status_code=400,
                        detail=f"El estudiante con código '{code}' ya está asignado a la Hoja {idx} ({other.source_name} - {other_display}). No se permite asignar un mismo estudiante a dos exámenes."
                    )

                if target_name and other_name and target_name == other_name:
                    other_display = f"{other.student_code} - {other.student_name}".strip(" - ")
                    raise HTTPException(
                        status_code=400,
                        detail=f"El estudiante '{name}' ya está asignado a la Hoja {idx} ({other.source_name} - {other_display}). No se permite asignar un mismo estudiante a dos exámenes."
                    )

    sheet.student_code = code
    sheet.student_name = name
    if not (code or name) and sheet.status == "approved":
        sheet.status = "review"
    return sheet_payload(sheet, with_answers=True)


def build_excel_file(batch: Batch, is_detailed_view: bool = False) -> io.BytesIO:
    approved = [sheet for sheet in batch.sheets if sheet.status == "approved"]
    if not approved:
        raise HTTPException(400, "Apruebe al menos una hoja antes de exportar")
    key = load_answer_key()

    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()

    font_header = Font(bold=True, color="FFFFFF", size=11)
    font_bold = Font(bold=True, size=10)
    font_gray = Font(size=10, color="8A99AD")
    font_correct = Font(bold=True, size=10, color="0D6130")
    font_incorrect = Font(bold=True, size=10, color="B52A10")

    fill_header_navy = PatternFill(start_color="1D3C6E", end_color="1D3C6E", fill_type="solid")
    fill_header_blue = PatternFill(start_color="2B579A", end_color="2B579A", fill_type="solid")
    fill_clave = PatternFill(start_color="FFF3CD", end_color="FFF3CD", fill_type="solid")
    fill_clave_q = PatternFill(start_color="D9E8FB", end_color="D9E8FB", fill_type="solid")
    fill_correct = PatternFill(start_color="D9F2E6", end_color="D9F2E6", fill_type="solid")
    fill_incorrect = PatternFill(start_color="FCE4EC", end_color="FCE4EC", fill_type="solid")
    fill_blank = PatternFill(start_color="F8F9FA", end_color="F8F9FA", fill_type="solid")
    fill_even_row = PatternFill(start_color="F7F9FC", end_color="F7F9FC", fill_type="solid")

    thin_border = Border(
        left=Side(style="thin", color="DCE4EE"),
        right=Side(style="thin", color="DCE4EE"),
        top=Side(style="thin", color="DCE4EE"),
        bottom=Side(style="thin", color="DCE4EE"),
    )
    align_center = Alignment(horizontal="center", vertical="center")
    align_left = Alignment(horizontal="left", vertical="center")
    align_header = Alignment(horizontal="center", vertical="center", wrap_text=True)

    # ================== HOJA: Respuestas Marcadas (P1-P140) ==================
    ws_matriz = wb.active
    ws_matriz.title = "Respuestas Marcadas (P1-P140)"

    matriz_headers = ["N°", "Código", "Estudiante", "Nota Final", "Aciertos", "Errores", "En Blanco"]
    for q in range(1, 141):
        matriz_headers.append(f"P{q}")

    ws_matriz.append(matriz_headers)
    for col_idx in range(1, len(matriz_headers) + 1):
        cell = ws_matriz.cell(row=1, column=col_idx)
        cell.font = font_header
        cell.fill = fill_header_navy if col_idx <= 7 else fill_header_blue
        cell.alignment = align_header
        cell.border = thin_border

    # Fila 2: Clave Oficial
    row_clave = ["", "", "CLAVE OFICIAL", "", "140", "", ""]
    for q in range(1, 141):
        row_clave.append(key.get(q, "-").strip().upper() or "-")
    ws_matriz.append(row_clave)
    for col_idx in range(1, len(row_clave) + 1):
        cell = ws_matriz.cell(row=2, column=col_idx)
        cell.border = thin_border
        cell.alignment = align_center
        cell.font = font_bold
        if col_idx == 3:
            cell.alignment = align_left
            cell.fill = fill_clave
        elif col_idx > 7:
            cell.fill = fill_clave_q

    student_start_row = 3
    correct_counts_per_q = {q: 0 for q in range(1, 141)}

    for idx, sheet in enumerate(approved, 1):
        student_display = f"{sheet.student_code} - {sheet.student_name}".strip(" - ") if (sheet.student_code or sheet.student_name) else ""
        row_student = [
            idx,
            sheet.student_code,
            sheet.student_name or student_display,
            round(sheet.score, 4),
            sheet.correct_count,
            sheet.incorrect_count,
            sheet.blank_count,
        ]

        ans_map = {a.question: a for a in sheet.answers}
        for q in range(1, 141):
            ans = ans_map.get(q)
            user_ans = (ans.answer if ans else "") or ""
            row_student.append(user_ans if user_ans else "-")

        ws_matriz.append(row_student)
        curr_row = student_start_row + idx - 1
        is_even = (idx % 2 == 0)

        for col_idx in range(1, 8):
            cell = ws_matriz.cell(row=curr_row, column=col_idx)
            cell.border = thin_border
            cell.alignment = align_left if col_idx == 3 else align_center
            if is_even:
                cell.fill = fill_even_row

        score_cell = ws_matriz.cell(row=curr_row, column=4)
        score_cell.number_format = '0.00'
        if sheet.score >= 50:
            score_cell.fill = fill_correct
            score_cell.font = font_correct
        else:
            score_cell.fill = fill_incorrect
            score_cell.font = font_incorrect

        for q in range(1, 141):
            col_idx = 7 + q
            cell = ws_matriz.cell(row=curr_row, column=col_idx)
            cell.border = thin_border
            cell.alignment = align_center

            ans = ans_map.get(q)
            user_ans = (ans.answer if ans else "").strip().upper() if ans else ""
            correct_ans = key.get(q, "").strip().upper()

            if not user_ans or (ans and ans.state == "blank"):
                cell.value = "-"
                cell.fill = fill_blank
                cell.font = font_gray
            elif user_ans == "DOBLE" or (ans and ans.state == "multiple") or len(user_ans) > 1:
                cell.value = user_ans
                cell.fill = fill_incorrect
                cell.font = font_incorrect
            elif correct_ans and user_ans == correct_ans:
                cell.value = user_ans
                cell.fill = fill_correct
                cell.font = font_correct
                correct_counts_per_q[q] += 1
            else:
                cell.value = user_ans
                cell.fill = fill_incorrect
                cell.font = font_incorrect

    # Filas estadísticas
    total_students = len(approved)
    stat_row_aciertos = ["", "", "TOTAL ACIERTOS", "", "", "", ""]
    stat_row_porcentaje = ["", "", "% ÉXITO", "", "", "", ""]
    for q in range(1, 141):
        c = correct_counts_per_q[q]
        stat_row_aciertos.append(c)
        pct = (c / total_students) if total_students > 0 else 0.0
        stat_row_porcentaje.append(round(pct * 100, 1))

    ws_matriz.append(stat_row_aciertos)
    row_aciertos_num = student_start_row + total_students
    for col_idx in range(1, len(stat_row_aciertos) + 1):
        cell = ws_matriz.cell(row=row_aciertos_num, column=col_idx)
        cell.border = thin_border
        cell.alignment = align_left if col_idx == 3 else align_center
        cell.font = font_bold
        if col_idx == 3 or col_idx > 7:
            cell.fill = fill_clave_q

    ws_matriz.append(stat_row_porcentaje)
    row_pct_num = row_aciertos_num + 1
    for col_idx in range(1, len(stat_row_porcentaje) + 1):
        cell = ws_matriz.cell(row=row_pct_num, column=col_idx)
        cell.border = thin_border
        cell.alignment = align_left if col_idx == 3 else align_center
        cell.font = font_bold
        if col_idx > 7:
            cell.number_format = '0.0"%"'
            cell.fill = fill_clave

    ws_matriz.column_dimensions["A"].width = 6
    ws_matriz.column_dimensions["B"].width = 15
    ws_matriz.column_dimensions["C"].width = 34
    ws_matriz.column_dimensions["D"].width = 12
    ws_matriz.column_dimensions["E"].width = 10
    ws_matriz.column_dimensions["F"].width = 10
    ws_matriz.column_dimensions["G"].width = 10
    for q in range(1, 141):
        ws_matriz.column_dimensions[get_column_letter(7 + q)].width = 5.2

    ws_matriz.freeze_panes = "H3"

    # ================== HOJA: Resumen ==================
    ws_resumen = wb.create_sheet(title="Resumen")
    resumen_headers = [
        "N°", "Código", "Estudiante", "Correctas", "Incorrectas",
        "En Blanco", "Nota Final", "Estado"
    ]
    ws_resumen.append(resumen_headers)
    for col_idx, _ in enumerate(resumen_headers, 1):
        cell = ws_resumen.cell(row=1, column=col_idx)
        cell.font = font_header
        cell.fill = fill_header_blue
        cell.alignment = align_header
        cell.border = thin_border

    for idx, sheet in enumerate(approved, 1):
        student_display = f"{sheet.student_code} - {sheet.student_name}".strip(" - ") if (sheet.student_code or sheet.student_name) else ""
        row_data = [
            idx,
            sheet.student_code,
            sheet.student_name or student_display,
            sheet.correct_count,
            sheet.incorrect_count,
            sheet.blank_count,
            round(sheet.score, 4),
            "Aprobado" if sheet.score >= 50 else "Desaprobado",
        ]
        ws_resumen.append(row_data)
        row_num = idx + 1
        for col_idx in range(1, len(row_data) + 1):
            cell = ws_resumen.cell(row=row_num, column=col_idx)
            cell.border = thin_border
            cell.alignment = align_left if col_idx == 3 else align_center
            if idx % 2 == 0:
                cell.fill = fill_even_row
        nota_cell = ws_resumen.cell(row=row_num, column=7)
        nota_cell.number_format = '0.00'
        estado_cell = ws_resumen.cell(row=row_num, column=8)
        if sheet.score >= 50:
            nota_cell.fill = fill_correct
            nota_cell.font = font_correct
            estado_cell.fill = fill_correct
            estado_cell.font = font_correct
        else:
            nota_cell.fill = fill_incorrect
            nota_cell.font = font_incorrect
            estado_cell.fill = fill_incorrect
            estado_cell.font = font_incorrect

    for col_idx, header in enumerate(resumen_headers, 1):
        max_len = len(header)
        for row in ws_resumen.iter_rows(min_row=2, min_col=col_idx, max_col=col_idx):
            for cell in row:
                if cell.value is not None:
                    max_len = max(max_len, len(str(cell.value)))
        ws_resumen.column_dimensions[ws_resumen.cell(row=1, column=col_idx).column_letter].width = min(max_len + 4, 40)

    # ================== HOJA: Detalle por Pregunta ==================
    ws_detalle = wb.create_sheet(title="Detalle por Pregunta")
    detalle_headers = [
        "Archivo", "Página", "Código Estudiante", "Estudiante",
        "Pregunta", "Clave", "Respuesta", "Resultado", "Puntos",
        "Nota Examen", "Estado", "Confianza"
    ]
    ws_detalle.append(detalle_headers)
    for col_idx, _ in enumerate(detalle_headers, 1):
        cell = ws_detalle.cell(row=1, column=col_idx)
        cell.font = font_header
        cell.fill = fill_header_blue
        cell.alignment = align_header
        cell.border = thin_border

    detail_row_num = 2
    for sheet in approved:
        student_display = f"{sheet.student_code} - {sheet.student_name}".strip(" - ") if (sheet.student_code or sheet.student_name) else ""
        for answer in sheet.answers:
            q = answer.question
            correct_ans = key.get(q, "").strip().upper()
            user_ans = (answer.answer or "").strip().upper()
            if not correct_ans:
                res = "BLANCO" if not user_ans else "SIN_CLAVE"
                pts = 0.0
            elif not user_ans or answer.state == "blank":
                res = "BLANCO"
                pts = 0.0
            elif answer.state in ("ok", "manual") and user_ans == correct_ans:
                res = "CORRECTA"
                pts = 1.0
            else:
                res = "INCORRECTA"
                pts = -0.01
            row_data = [
                sheet.source_name,
                sheet.page_number or "",
                sheet.student_code,
                sheet.student_name or student_display,
                q,
                correct_ans,
                user_ans,
                res,
                pts,
                round(sheet.score, 4),
                answer.state,
                answer.confidence,
            ]
            ws_detalle.append(row_data)
            for col_idx in range(1, len(row_data) + 1):
                cell = ws_detalle.cell(row=detail_row_num, column=col_idx)
                cell.border = thin_border
                cell.alignment = align_center
            res_cell = ws_detalle.cell(row=detail_row_num, column=8)
            if res == "CORRECTA":
                res_cell.fill = fill_correct
                res_cell.font = font_correct
            elif res == "INCORRECTA":
                res_cell.fill = fill_incorrect
                res_cell.font = font_incorrect
            detail_row_num += 1

    for col_idx, header in enumerate(detalle_headers, 1):
        max_len = len(header)
        for row in ws_detalle.iter_rows(min_row=2, min_col=col_idx, max_col=col_idx):
            for cell in row:
                if cell.value is not None:
                    max_len = max(max_len, len(str(cell.value)))
        ws_detalle.column_dimensions[ws_detalle.cell(row=1, column=col_idx).column_letter].width = min(max_len + 4, 40)

    if is_detailed_view:
        wb.active = ws_matriz
        wb._sheets = [ws_matriz, ws_resumen, ws_detalle]
    else:
        wb.active = ws_resumen
        wb._sheets = [ws_resumen, ws_matriz, ws_detalle]

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output


@app.get("/api/batches/{batch_id}/export.xlsx")
def export_xlsx(batch_id: str):
    batch = BATCHES.get(batch_id)
    if not batch:
        raise HTTPException(404, "Lote no encontrado")
    output = build_excel_file(batch, is_detailed_view=False)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=resultados-omr.xlsx"},
    )


@app.get("/api/batches/{batch_id}/export-detailed.xlsx")
def export_detailed_xlsx(batch_id: str):
    batch = BATCHES.get(batch_id)
    if not batch:
        raise HTTPException(404, "Lote no encontrado")
    output = build_excel_file(batch, is_detailed_view=True)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=respuestas-detalladas-omr.xlsx"},
    )


@app.get("/api/batches/{batch_id}/results")
def get_batch_results(batch_id: str):
    batch = BATCHES.get(batch_id)
    if not batch:
        raise HTTPException(404, "Lote no encontrado")
    approved = [sheet for sheet in batch.sheets if sheet.status == "approved"]
    results = []
    for idx, sheet in enumerate(approved, 1):
        student_display = f"{sheet.student_code} - {sheet.student_name}".strip(" - ") if (sheet.student_code or sheet.student_name) else ""
        results.append({
            "number": idx,
            "sheet_id": sheet.id,
            "student_code": sheet.student_code,
            "student_name": sheet.student_name,
            "student": student_display,
            "correct_count": sheet.correct_count,
            "incorrect_count": sheet.incorrect_count,
            "blank_count": sheet.blank_count,
            "score": round(sheet.score, 4),
            "source_name": sheet.source_name,
            "page_number": sheet.page_number,
        })
    return {"results": results, "total": len(results)}


app.mount("/", StaticFiles(directory=ROOT / "app" / "static", html=True), name="static")

