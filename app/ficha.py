"""Genera la ficha óptica alineada a la cuadrícula del lector (1280 x 920)."""

from __future__ import annotations

import math
from pathlib import Path

import pymupdf

from app.grid import BLOCKS, CANVAS_H, CANVAS_W, OPTIONS, OPTION_DX, ROW_DY, center

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "app" / "static" / "ficha-omr.pdf"
PAGE_W, PAGE_H = pymupdf.paper_size("a4-l")
SX, SY = PAGE_W / CANVAS_W, PAGE_H / CANVAS_H
BUBBLE_R = 7.5 * SX


def p(x: float, y: float) -> pymupdf.Point:
    return pymupdf.Point(x * SX, y * SY)


def r(x0: float, y0: float, x1: float, y1: float) -> pymupdf.Rect:
    return pymupdf.Rect(x0 * SX, y0 * SY, x1 * SX, y1 * SY)


def text(page: pymupdf.Page, x: float, y: float, value: str, size: float = 7, bold: bool = False) -> None:
    page.insert_text(p(x, y), value, fontname="hebo" if bold else "helv", fontsize=size, color=(0, 0, 0))


def draw_bubble(page: pymupdf.Page, x: float, y: float, filled: bool = False, label: str | None = None) -> None:
    page.draw_circle(p(x, y), BUBBLE_R, color=(0, 0, 0), fill=(0, 0, 0) if filled else None, width=0.65)
    if label:
        text(page, x - 2.2, y + 2.1, label, size=4.8)


def seal(page: pymupdf.Page, x: float, y: float) -> None:
    page.draw_circle(p(x, y), 24 * SX, color=(0, 0, 0), width=1.35)
    page.draw_circle(p(x, y), 18 * SX, color=(0, 0, 0), width=0.45)
    for angle in range(0, 360, 30):
        rad = math.radians(angle)
        inner, outer = 6.5, 15
        page.draw_line(
            p(x + inner * math.cos(rad), y + inner * math.sin(rad)),
            p(x + outer * math.cos(rad), y + outer * math.sin(rad)),
            color=(0, 0, 0),
            width=0.5,
        )
    text(page, x - 8, y + 3, "UNU", size=7, bold=True)


def header(page: pymupdf.Page, x: float, title: str) -> None:
    seal(page, x + 28, 36)
    text(page, x + 58, 24, "UNIVERSIDAD NACIONAL DE UCAYALI", size=9, bold=True)
    text(page, x + 58, 38, "COMISIÓN DE ADMISIÓN", size=8, bold=True)
    text(page, x + 58, 51, "PUCALLPA - PERÚ", size=7)
    text(page, x + 58, 72, title, size=11, bold=True)


def timing_marks(page: pymupdf.Page, x: float, top: float, bottom: float, count: int = 18) -> None:
    step = (bottom - top) / (count - 1)
    for index in range(count):
        y = top + index * step
        page.draw_rect(r(x, y, x + 10, y + 8), color=(0, 0, 0), fill=(0, 0, 0), width=0)


def identification(page: pymupdf.Page) -> None:
    header(page, 18, "HOJA DE IDENTIFICACIÓN")
    timing_marks(page, 6, 92, 872)
    page.insert_text(p(16, 900), "NO ESCRIBA EN ESTA ÁREA", fontname="hebo", fontsize=5, rotate=90)

    page.draw_rect(r(30, 86, 300, 126), color=(0, 0, 0), width=0.7)
    text(page, 36, 100, "PABELLÓN", size=7, bold=True)
    page.draw_rect(r(312, 86, 600, 126), color=(0, 0, 0), width=0.7)
    text(page, 318, 100, "AULA", size=7, bold=True)

    for label, y in (("APELLIDO PATERNO", 138), ("APELLIDO MATERNO", 186), ("NOMBRES", 234)):
        page.draw_rect(r(30, y, 600, y + 40), color=(0, 0, 0), width=0.7)
        text(page, 36, y + 14, label, size=7, bold=True)

    text(page, 30, 294, "NÚMERO DE DNI", size=8, bold=True)
    origin_x, origin_y = 72, 336
    for column in range(8):
        cx = origin_x + column * 62
        page.draw_rect(r(cx - 16, 304, cx + 16, 322), color=(0, 0, 0), width=0.5)
        for digit in range(10):
            x, y = cx, origin_y + digit * 22
            draw_bubble(page, x, y, label=str(digit))

    text(page, 30, 568, "EJEMPLOS DE MARCAS", size=7, bold=True)
    samples = [
        (58, "CORRECTA", True, None),
        (128, "INCORRECTA", False, "tick"),
        (198, "", False, "x"),
        (268, "", False, "slash"),
        (338, "", False, "open"),
    ]
    for x, label, filled, extra in samples:
        draw_bubble(page, x, 596, filled=filled)
        if extra == "tick":
            page.draw_polyline([p(x - 4, 596), p(x - 1, 599), p(x + 5, 592)], color=(0, 0, 0), width=0.8)
        elif extra == "x":
            page.draw_line(p(x - 4, 592), p(x + 4, 600), color=(0, 0, 0), width=0.8)
            page.draw_line(p(x + 4, 592), p(x - 4, 600), color=(0, 0, 0), width=0.8)
        elif extra == "slash":
            page.draw_line(p(x - 5, 600), p(x + 5, 592), color=(0, 0, 0), width=0.8)
        elif extra == "open":
            page.draw_polyline([p(x - 5, 596), p(x, 590), p(x + 5, 596)], color=(0, 0, 0), width=0.8)
        if label:
            text(page, x - 18, 614, label, size=5)

    page.draw_rect(r(30, 640, 600, 872), color=(0, 0, 0), width=0.7)
    text(page, 36, 656, "FIRMA DEL POSTULANTE (dentro del recuadro)", size=7, bold=True)


def answers(page: pymupdf.Page) -> None:
    header(page, 630, "HOJA DE RESPUESTAS")
    timing_marks(page, 1264, 92, 872)
    page.draw_rect(r(638, 82, 1252, 138), color=(0, 0, 0), width=0.65)
    page.insert_textbox(
        r(646, 86, 1244, 134),
        "INSTRUCCIONES: Use solo lápiz 2B. No use tinta ni lapicero. Rellene el círculo por completo. "
        "Si se equivoca, borre con cuidado. No doble ni maltrate la hoja. 140 preguntas · alternativas A-E.",
        fontname="helv",
        fontsize=7,
    )
    text(page, 638, 158, "TIPO DE PRUEBA", size=7, bold=True)
    for index, letter in enumerate(OPTIONS):
        x = 760 + index * 28
        draw_bubble(page, x, 166, label=letter)

    for block in range(4):
        first = block * 35 + 1
        last = first + 34
        ax, ay = center(block, 0, 0)
        text(page, ax - 8, 186, f"{first:03d}-{last:03d}", size=6, bold=True)
        for row in range(35):
            qx, qy = center(block, row, 0)
            text(page, qx - 22, qy + 2.4, f"{first + row:03d}", size=5.5)
            for option in range(5):
                draw_bubble(page, *center(block, row, option), label=OPTIONS[option])


def generate(path: Path = OUTPUT) -> Path:
    document = pymupdf.open()
    page = document.new_page(width=PAGE_W, height=PAGE_H)
    page.draw_rect(pymupdf.Rect(7, 7, PAGE_W - 7, PAGE_H - 7), color=(0, 0, 0), width=1.05)
    identification(page)
    page.draw_line(p(618, 14), p(618, 906), color=(0, 0, 0), width=0.55, dashes="[2 2]")
    answers(page)
    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(path)
    document.close()
    return path


if __name__ == "__main__":
    print(generate())
