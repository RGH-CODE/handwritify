"""
ocr.py
Turns a photo/scan of a page into an ordered list of items:
paragraphs of text and pictures (diagrams, figures, photos).

How pictures are found (no ML needed):
  1. Tesseract reports where every word is.
  2. Word boxes are erased from the page's ink; what remains is
     "ink that is not text".
  3. Nearby leftovers are merged; big enough blobs become pictures.
  4. Words that fall inside a picture (labels on a diagram) stay with the
     picture instead of leaking into the text.
Pictures are cropped from the deskewed *colour* photo, so they keep detail.

Requires the Tesseract binary (see README).
"""
from __future__ import annotations

from typing import Dict, List, Tuple

import cv2
import numpy as np
import pytesseract
from PIL import Image
from pytesseract import Output

from .markup import reflow
from .models import ImageItem, Item, TextItem, flatten_rgb

MAX_SIDE = 3200   # phone photos are downscaled: OCR doesn't need more
MIN_SIDE = 1400   # tiny screenshots are upscaled so Tesseract can read them
MAX_FIGURES_PER_PAGE = 8


# --------------------------------------------------------------------------
# Page preparation
# --------------------------------------------------------------------------
def _rotate(arr: np.ndarray, angle: float, border=cv2.BORDER_REPLICATE) -> np.ndarray:
    h, w = arr.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(arr, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=border)


def _estimate_skew(gray: np.ndarray) -> float:
    """Angle (degrees) to rotate by so text lines become horizontal.
    Picks the rotation whose row-ink profile is sharpest -- robust to shadows
    and page edges, unlike bounding-box methods."""
    h, w = gray.shape
    scale = min(1.0, 900.0 / max(h, w))
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else gray
    ink = cv2.adaptiveThreshold(small, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                cv2.THRESH_BINARY_INV, 21, 12)

    def score(a: float) -> float:
        r = _rotate(ink, a, cv2.BORDER_CONSTANT)
        proj = r.sum(axis=1, dtype=np.float64) / 255.0
        return float(np.sum(np.diff(proj) ** 2))

    best = max(np.arange(-8, 8.01, 1.0), key=score)
    return float(max(np.arange(best - 1, best + 1.01, 0.2), key=score))


def prepare_page(image: Image.Image) -> Tuple[Image.Image, Image.Image]:
    """Returns (deskewed colour page, binarised page for OCR)."""
    rgb = np.array(flatten_rgb(image))
    h, w = rgb.shape[:2]
    longest = max(h, w)
    if longest > MAX_SIDE:
        rgb = cv2.resize(rgb, None, fx=MAX_SIDE / longest, fy=MAX_SIDE / longest,
                         interpolation=cv2.INTER_AREA)
    elif longest < MIN_SIDE:
        rgb = cv2.resize(rgb, None, fx=MIN_SIDE / longest, fy=MIN_SIDE / longest,
                         interpolation=cv2.INTER_CUBIC)

    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    angle = _estimate_skew(gray)
    if abs(angle) >= 0.3:
        rgb = _rotate(rgb, angle)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

    binary = cv2.adaptiveThreshold(cv2.GaussianBlur(gray, (3, 3), 0), 255,
                                   cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY, 31, 15)
    return Image.fromarray(rgb), Image.fromarray(binary)


# --------------------------------------------------------------------------
# Picture (figure) detection
# --------------------------------------------------------------------------
Box = Tuple[int, int, int, int]  # x, y, w, h


def _near(a: Box, b: Box, gap: int) -> bool:
    return (a[0] - gap < b[0] + b[2] and b[0] - gap < a[0] + a[2] and
            a[1] - gap < b[1] + b[3] and b[1] - gap < a[1] + a[3])


def _union(a: Box, b: Box) -> Box:
    x, y = min(a[0], b[0]), min(a[1], b[1])
    return (x, y, max(a[0] + a[2], b[0] + b[2]) - x, max(a[1] + a[3], b[1] + b[3]) - y)


def _merge_boxes(boxes: List[Box], gap: int) -> List[Box]:
    boxes = list(boxes)
    merged = True
    while merged:
        merged = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                if _near(boxes[i], boxes[j], gap):
                    boxes[i] = _union(boxes[i], boxes[j])
                    del boxes[j]
                    merged = True
                    break
            if merged:
                break
    return boxes


def find_figures(binary: Image.Image, words: List[Dict]) -> List[Box]:
    """Bounding boxes of non-text ink (diagrams, photos, tables drawn as art)."""
    ink = (255 - np.array(binary)).astype(np.uint8)
    H, W = ink.shape

    heights = [w["h"] for w in words if w["conf"] >= 60 and w["h"] >= 6]
    h_med = float(np.median(heights)) if len(heights) >= 5 else max(20.0, H / 70)

    # erase recognised text (plausible size only, so garbage "words" that
    # Tesseract hallucinates inside a picture don't erase the picture)
    mask = ink.copy()
    for w in words:
        if w["conf"] >= 40 and 0.4 * h_med <= w["h"] <= 2.6 * h_med:
            pad = max(2, int(0.2 * w["h"]))
            mask[max(0, w["y"] - pad):w["y"] + w["h"] + pad,
                 max(0, w["x"] - pad):w["x"] + w["w"] + pad] = 0

    # drop isolated specks but keep thin long strokes (diagram lines)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    keep = stats[:, cv2.CC_STAT_AREA] >= 12
    keep[0] = False
    mask = (keep[labels] * 255).astype(np.uint8)

    k = max(9, int(h_med * 1.1))
    merged = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                              cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    contours, _ = cv2.findContours(merged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    min_dim = 0.3 * h_med
    boxes = [cv2.boundingRect(c) for c in contours]
    boxes = [b for b in boxes if b[2] >= min_dim and b[3] >= min_dim]
    boxes = _merge_boxes(boxes, gap=int(1.5 * h_med))

    figures: List[Box] = []
    for (x, y, w, h) in boxes:
        if w < 3 * h_med or h < 3 * h_med:          # too small to be a picture
            continue
        if w * h > 0.7 * W * H:                     # page edge / shadow, not a figure
            continue
        density = np.count_nonzero(mask[y:y + h, x:x + w]) / float(w * h)
        if density < 0.015:                         # practically empty
            continue
        figures.append((x, y, w, h))

    figures.sort(key=lambda b: b[2] * b[3], reverse=True)
    return sorted(figures[:MAX_FIGURES_PER_PAGE], key=lambda b: (b[1], b[0]))


# --------------------------------------------------------------------------
# Page -> ordered items
# --------------------------------------------------------------------------
def analyze_page(image: Image.Image, detect_figures: bool = True) -> List[Item]:
    color, binary = prepare_page(image)
    try:
        data = pytesseract.image_to_data(binary, output_type=Output.DICT)
    except pytesseract.TesseractNotFoundError:
        raise RuntimeError(
            "Tesseract is not installed on this machine. "
            "See README.md for the one-line install command for your OS."
        )

    words: List[Dict] = []
    for i, raw in enumerate(data["text"]):
        text = raw.strip()
        if not text:
            continue
        words.append({
            "text": text, "conf": float(data["conf"][i]),
            "x": data["left"][i], "y": data["top"][i],
            "w": data["width"][i], "h": data["height"][i],
            "block": data["block_num"][i], "par": data["par_num"][i],
            "line": data["line_num"][i],
        })

    figures = find_figures(binary, words) if detect_figures else []

    def inside_figure(w: Dict) -> bool:
        cx, cy = w["x"] + w["w"] / 2, w["y"] + w["h"] / 2
        return any(fx <= cx <= fx + fw and fy <= cy <= fy + fh for fx, fy, fw, fh in figures)

    # group the good words into paragraphs -> lines, in Tesseract's reading order
    paragraphs: Dict[Tuple[int, int], Dict] = {}
    for w in words:
        if w["conf"] < 30 or inside_figure(w):
            continue
        p = paragraphs.setdefault((w["block"], w["par"]), {"top": w["y"], "lines": {}})
        p["top"] = min(p["top"], w["y"])
        p["lines"].setdefault(w["line"], []).append(w["text"])

    Wc, Hc = color.size
    outside = [w for w in words if w["conf"] >= 40 and not inside_figure(w)]
    crops = []
    for (x, y, w, h) in figures:
        pad = 10
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1, y1 = min(Wc, x + w + pad), min(Hc, y + h + pad)
        crop = np.array(color.crop((x0, y0, x1, y1)))
        # paint out neighbouring text (previous/next lines) that intrudes into the crop
        bg = np.percentile(crop.reshape(-1, 3), 85, axis=0).astype(np.uint8)
        for t in outside:
            ix0, iy0 = max(t["x"] - 2, x0), max(t["y"] - 2, y0)
            ix1, iy1 = min(t["x"] + t["w"] + 2, x1), min(t["y"] + t["h"] + 2, y1)
            if ix0 < ix1 and iy0 < iy1:
                crop[iy0 - y0:iy1 - y0, ix0 - x0:ix1 - x0] = bg
        crops.append((y, Image.fromarray(crop)))

    items: List[Item] = []
    pending = list(crops)
    for p in paragraphs.values():
        while pending and pending[0][0] <= p["top"]:
            items.append(ImageItem(pending.pop(0)[1]))
        text = reflow("\n".join(" ".join(ws) for ws in p["lines"].values()))
        if text:
            items.append(TextItem(text))
    items.extend(ImageItem(c) for _, c in pending)
    return items
