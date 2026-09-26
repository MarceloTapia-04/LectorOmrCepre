"""Cuadrícula de 140 preguntas (4 bloques × 35 × A-E) sobre el lienzo 1280×920."""

from __future__ import annotations

import cv2
import numpy as np

CANVAS_W, CANVAS_H = 1280, 920
OPTIONS = "ABCDE"
BLOCKS = [(636.6, 208.6), (788.6, 208.6), (946.6, 209.4), (1100.2, 210.2)]
OPTION_DX = 19.5
ROW_DY = 19.2
BLOCK_WINDOWS = ((620, 730), (770, 880), (930, 1040), (1085, 1210))


def center(block: int, row: int, option: int) -> tuple[float, float]:
    x, y = BLOCKS[block]
    return x + option * OPTION_DX, y + row * ROW_DY


def _cluster(values: np.ndarray, gap: float, minimum: int) -> np.ndarray:
    if len(values) == 0:
        return np.array([], dtype=float)
    ordered = np.sort(values)
    groups = [[ordered[0]]]
    for value in ordered[1:]:
        if value - groups[-1][-1] <= gap:
            groups[-1].append(value)
        else:
            groups.append([value])
    return np.array([float(np.median(group)) for group in groups if len(group) >= minimum])


def detect_grid(image: np.ndarray) -> list[dict[str, float]] | None:
    """Localiza A/E de la primera y última pregunta de cada bloque."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    found = cv2.HoughCircles(blur, cv2.HOUGH_GRADIENT, dp=1.2, minDist=9, param1=70, param2=16, minRadius=4, maxRadius=10)
    if found is None:
        return None
    bubbles = found[0]
    answer_area = bubbles[(bubbles[:, 0] > 600) & (bubbles[:, 1] > 190) & (bubbles[:, 1] < 890)]
    points: list[dict[str, float]] = []
    for left, right in BLOCK_WINDOWS:
        column = answer_area[(answer_area[:, 0] >= left) & (answer_area[:, 0] <= right)]
        xs = _cluster(column[:, 0], 6, 10)
        ys = _cluster(column[:, 1], 5, 3)
        if len(xs) < 5 or len(ys) < 35:
            return None
        xs, ys = xs[:5], ys[:35]
        for row in (0, 34):
            for option in (0, 4):
                points.append({"x": round(float(xs[option]), 2), "y": round(float(ys[row]), 2)})
    return points if len(points) == 16 else None
