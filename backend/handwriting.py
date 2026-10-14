"""
handwriting.py
Renders the editable document (see markup.py) as handwritten-looking pages.

Engine: handwriting font + per-character jitter (tiny rotation, size and ink
variation, baseline drift). Not a neural stroke model -- see README.

"Formats" = any .ttf/.otf dropped into fonts/. The file name (without
extension) is the style name shown in the UI.
"""
from __future__ import annotations

import math
import os
import random
import re
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFont

from .markup import parse_markup
from .schemas import RenderSettings

FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fonts")
DPI = 200
PAGE_SIZES = {"a4": (1654, 2339), "a5": (1157, 1654), "letter": (1700, 2200),
              "canvas": (3307, 3307)}


def mm(v: float) -> int:
    return int(round(v / 25.4 * DPI))


@dataclass
class PaperStyle:
    key: str
    name: str


PAPER_STYLES = [
    PaperStyle("ruled", "Ruled paper"),
    PaperStyle("grid", "Grid paper"),
    PaperStyle("blank", "Blank page"),
]

# characters most handwriting fonts don't have -> safe look-alikes
_LIGATURES = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl"}
_BULLET_GLYPH = "\ue000"
_CHAR_FIXES = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'",
                             "–": "-", "—": "-", "…": "...", "\u00a0": " ",
                             "•": _BULLET_GLYPH, "·": _BULLET_GLYPH,
                             "‣": _BULLET_GLYPH, "◦": _BULLET_GLYPH,
                             "▪": _BULLET_GLYPH, "▫": _BULLET_GLYPH,
                             "●": _BULLET_GLYPH, "○": _BULLET_GLYPH,
                             "→": "->", "←": "<-", "↔": "<->",
                             "⇒": "=>", "⇐": "<=", "⇔": "<=>",
                             "↑": "^", "↓": "v"})


def _normalize(text: str) -> str:
    for k, v in _LIGATURES.items():
        text = text.replace(k, v)
    text = text.translate(_CHAR_FIXES)
    lines = []
    for line in text.splitlines():
        if re.match(r"^\s*¢(?:\s|«)", line):
            line = re.sub(r"¢\s*«?\s*", _BULLET_GLYPH + " ", line)
            line = re.sub(r"(?<=\S)[ \t]+" + re.escape(_BULLET_GLYPH),
                          "\n" + _BULLET_GLYPH + " ", line)
        lines.append(line)
    return "\n".join(lines)


# ---------------------------------------------------------------- fonts
def _font_file(style: str) -> Optional[str]:
    if not style or not os.path.isdir(FONTS_DIR):
        return None
    for f in os.listdir(FONTS_DIR):
        stem, ext = os.path.splitext(f)
        if stem == style and ext.lower() in (".ttf", ".otf"):
            return os.path.join(FONTS_DIR, f)
    return None


def list_fonts() -> List[str]:
    if not os.path.isdir(FONTS_DIR):
        return []
    return sorted(os.path.splitext(f)[0] for f in os.listdir(FONTS_DIR)
                  if f.lower().endswith((".ttf", ".otf")))


def font_family_name(style: str) -> str:
    """The family name Word needs (read from the font file itself)."""
    path = _font_file(style)
    if path:
        try:
            return ImageFont.truetype(path, 20).getname()[0]
        except Exception:
            pass
    return style or "Calibri"


_FONT_CACHE: Dict[Tuple[str, int], ImageFont.FreeTypeFont] = {}


def _load_font(style: str, size: int) -> ImageFont.FreeTypeFont:
    key = (style, size)
    if key not in _FONT_CACHE:
        path = _font_file(style)
        # fallback keeps the app running before any real handwriting font is added
        _FONT_CACHE[key] = ImageFont.truetype(path, size) if path else ImageFont.load_default(size)
    return _FONT_CACHE[key]


# ------------------------------------------------------- picture styling
def _tint(darkness: np.ndarray, ink_color: str) -> Image.Image:
    """darkness 0..255 (255 = full ink) -> RGB image, ink on white."""
    ink = np.array([int(ink_color[i:i + 2], 16) for i in (1, 3, 5)], dtype=np.float32)
    a = (darkness.astype(np.float32) / 255.0)[..., None]
    return Image.fromarray((255.0 - a * (255.0 - ink)).astype(np.uint8))


def process_image(img: Image.Image, mode: str, ink_color: str) -> Optional[Image.Image]:
    """Restyle a picture found in the source pages so it suits the notes."""
    if mode == "skip":
        return None
    rgb = img.convert("RGB")
    if mode == "original":
        return rgb
    gray = cv2.cvtColor(np.array(rgb), cv2.COLOR_RGB2GRAY)
    if mode == "grayscale":
        return Image.fromarray(gray).convert("RGB")
    if mode == "sketch":  # pencil-sketch: colour-dodge of the image with its blurred negative
        enhanced = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
        blur = cv2.GaussianBlur(255 - enhanced, (0, 0), max(2.0, min(gray.shape) / 90.0))
        dodge = cv2.divide(enhanced, 255 - blur, scale=256)
        dark = np.clip((255.0 - dodge.astype(np.float32) - 5.0) * 1.7, 0, 255)
        return _tint(dark, ink_color)
    if mode == "ink":  # clean line-art
        block = max(15, (min(gray.shape) // 16) | 1)
        bw = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY, block, 6)
        return _tint(255 - bw, ink_color)
    return rgb


# -------------------------------------------------------------- renderer
class _Renderer:
    def __init__(self, s: RenderSettings, images: Dict[str, Image.Image],
                 page_sink: Optional[Callable[[Image.Image], None]] = None):
        self.s = s
        self.page_sink = page_sink
        self.rng = random.Random(s.seed)
        self.W, self.H = PAGE_SIZES[s.page_size]
        self.mt, self.mb = mm(s.margin_top_mm), mm(s.margin_bottom_mm)
        self.ml, self.mr = mm(s.margin_left_mm), mm(s.margin_right_mm)
        self.pitch = max(10, int(round(s.font_size * s.line_spacing)))  # line-to-line distance
        self.text_w = max(200, self.W - self.ml - self.mr)
        self.bottom = self.H - self.mb
        self.raw_images = images
        self._proc: Dict[str, Optional[Image.Image]] = {}
        self._adv: Dict[Tuple[int, str], float] = {}
        self._glyphs: Dict[tuple, tuple] = {}
        self.pages: List[Image.Image] = []
        self.page_count = 0
        self._page_active = False
        self.img: Image.Image
        self.draw: ImageDraw.ImageDraw
        self.y = 0      # baseline of the next line to write
        self.empty = True
        self.new_page()

    # ---- pages
    def _emit_page(self):
        if self.s.page_numbers:
            font = self.font(int(self.s.font_size * 0.6))
            ImageDraw.Draw(self.img).text((self.W / 2, self.H - self.mb / 2),
                                          str(self.page_count + 1), font=font,
                                          fill=self.s.ink_color, anchor="mm")
        if self.page_sink is None:
            self.pages.append(self.img)
        else:
            self.page_sink(self.img)
        self.page_count += 1

    def new_page(self):
        if self._page_active:
            self._emit_page()
        paper = tuple(int(self.s.paper_color[i:i + 2], 16) for i in (1, 3, 5))
        self.img = Image.new("RGB", (self.W, self.H), paper)
        self.draw = ImageDraw.Draw(self.img)
        self._page_active = True
        self.y = self.mt + self.pitch
        self.empty = True
        self._draw_paper()

    def _draw_paper(self):
        d, s = self.draw, self.s
        if s.paper == "ruled":
            y = self.mt + self.pitch
            while y <= self.bottom:
                d.line([(self.ml - 25, y + 3), (self.W - self.mr + 20, y + 3)],
                       fill=(188, 204, 232), width=2)
                y += self.pitch
            d.line([(self.ml - 40, 0), (self.ml - 40, self.H)], fill=(232, 150, 150), width=2)
        elif s.paper == "grid":
            step = 39  # ~5 mm squares
            for x in range(0, self.W, step):
                d.line([(x, 0), (x, self.H)], fill=(222, 228, 236), width=1)
            for y in range(0, self.H, step):
                d.line([(0, y), (self.W, y)], fill=(222, 228, 236), width=1)

    def ensure_space(self, lines: int = 1):
        if self.y + (lines - 1) * self.pitch > self.bottom:
            self.new_page()

    # ---- measuring
    def font(self, size: int):
        return _load_font(self.s.style, size)

    def adv(self, size: int, ch: str) -> float:
        k = (size, ch)
        if k not in self._adv:
            self._adv[k] = size * 0.42 if ch == _BULLET_GLYPH else self.font(size).getlength(ch)
        return self._adv[k]

    def word_w(self, word: str, size: int) -> float:
        return sum(self.adv(size, c) for c in word) + self.s.letter_spacing * len(word)

    def space_w(self, size: int) -> float:
        return max(size * 0.22, self.adv(size, " ")) * self.s.word_spacing

    def _split_long(self, word: str, size: int, width: float) -> List[str]:
        parts, cur = [], ""
        for c in word:
            if cur and self.word_w(cur + c, size) > width:
                parts.append(cur)
                cur = c
            else:
                cur += c
        return parts + [cur]

    def wrap(self, words: List[str], size: int, width: float, indent: float = 0) -> List[List[str]]:
        lines: List[List[str]] = []
        cur: List[str] = []
        cur_w, avail, sp = 0.0, width - indent, self.space_w(size)
        for w in words:
            ww = self.word_w(w, size)
            if ww > width:  # unbreakable and wider than the page: hard-split
                if cur:
                    lines.append(cur)
                    cur, cur_w = [], 0.0
                pieces = self._split_long(w, size, width)
                lines.extend([p] for p in pieces[:-1])
                cur, cur_w, avail = [pieces[-1]], self.word_w(pieces[-1], size), width
                continue
            add = ww if not cur else sp + ww
            if cur and cur_w + add > avail:
                lines.append(cur)
                cur, cur_w, avail = [w], ww, width
            else:
                cur.append(w)
                cur_w += add
        if cur:
            lines.append(cur)
        return lines

    # ---- drawing
    def _glyph(self, ch: str, size: int, angle: int, alpha_i: int):
        key = (ch, size, angle, alpha_i)
        g = self._glyphs.get(key)
        if g is None:
            font = self.font(size)
            asc, desc = font.getmetrics()
            pad = int(size * 0.3)
            adv = (max(1, int(size * 0.42)) if ch == _BULLET_GLYPH
                   else max(1, int(math.ceil(font.getlength(ch)))))
            canvas = Image.new("RGBA", (adv + 2 * pad, asc + desc + 2 * pad), (0, 0, 0, 0))
            glyph_draw = ImageDraw.Draw(canvas)
            if ch == _BULLET_GLYPH:
                radius = max(2, int(size * 0.08))
                center_x = pad + adv / 2
                center_y = pad + asc - size * 0.34
                glyph_draw.ellipse((center_x - radius, center_y - radius,
                                    center_x + radius, center_y + radius),
                                   fill=self.s.ink_color)
            else:
                glyph_draw.text((pad, pad + asc), ch, font=font,
                                fill=self.s.ink_color, anchor="ls")
            if angle:  # rotate about the baseline start so lines stay level
                canvas = canvas.rotate(angle, resample=Image.BICUBIC, center=(pad, pad + asc))
            if alpha_i:
                a = canvas.getchannel("A").point(lambda v: int(v * 0.88))
                canvas.putalpha(a)
            g = (canvas, pad, pad + asc)
            self._glyphs[key] = g
        return g

    def draw_words(self, words: List[str], x0: float, avail: float, size: int,
                   align: str, justify: bool) -> Tuple[float, float]:
        s, rng = self.s, self.rng
        widths = [self.word_w(w, size) for w in words]
        sp = self.space_w(size)
        total = sum(widths) + sp * (len(words) - 1)
        gap, x = sp, x0
        if justify and len(words) > 1:
            stretched = (avail - sum(widths)) / (len(words) - 1)
            if sp * 0.6 <= stretched <= sp * 3:
                gap = stretched
                total = avail
        elif align == "center":
            x = x0 + (avail - total) / 2
        elif align == "right":
            x = x0 + avail - total
        left = x
        phase = rng.uniform(0, 6.28)
        jit = s.jitter
        for w, ww in zip(words, widths):
            for ch in w:
                angle = int(round(rng.uniform(-2.5, 2.5) * jit))
                dsz = rng.choice((-1, 0, 0, 1)) if jit > 0.3 else 0
                alpha_i = rng.choice((0, 1)) if jit > 0 else 0
                drift = math.sin(x / 260.0 + phase) * 1.2 * jit
                dy = rng.uniform(-1.5, 1.5) * jit + drift
                glyph, ox, oy = self._glyph(ch, max(8, size + dsz), angle, alpha_i)
                self.img.paste(glyph, (int(x) - ox, int(self.y + dy) - oy), glyph)
                x += self.adv(size, ch) + s.letter_spacing + rng.uniform(-0.4, 0.4) * jit
            x += gap
        self.empty = False
        return left, left + total

    # ---- blocks
    def snap_gap(self, lines: float) -> int:
        """Vertical gap in px; on ruled paper whole lines so text stays on the rules."""
        if self.s.paper == "ruled":
            return int(math.floor(lines + 0.5)) * self.pitch
        return int(round(lines * self.pitch))

    def paragraph(self, lines: List[str]):
        s = self.s
        for li, hard in enumerate(lines):
            words = hard.split()
            if not words:
                continue
            indent = mm(s.first_line_indent_mm) if li == 0 else 0
            wrapped = self.wrap(words, s.font_size, self.text_w, indent)
            for k, ln in enumerate(wrapped):
                self.ensure_space(1)
                ind = indent if k == 0 else 0
                last = k == len(wrapped) - 1
                self.draw_words(ln, self.ml + ind, self.text_w - ind, s.font_size,
                                s.align, s.align == "justify" and not last)
                self.y += self.pitch
        self.y += self.snap_gap(s.paragraph_gap)

    def heading(self, text: str):
        s = self.s
        size = int(s.font_size * s.heading_scale)
        n = max(1, math.ceil(size * s.line_spacing / self.pitch))  # ruled lines it occupies
        align = s.align if s.align in ("center", "right") else "left"
        for ln in self.wrap(text.split(), size, self.text_w):
            self.ensure_space(n)
            self.y += (n - 1) * self.pitch
            left, right = self.draw_words(ln, self.ml, self.text_w, size, align, False)
            self._underline(left, right, self.y + int(size * 0.18))
            self.y += self.pitch
        self.y += self.snap_gap(s.paragraph_gap)

    def _underline(self, x0: float, x1: float, y: float):
        pts, x = [], x0
        while x < x1:
            pts.append((x, y + self.rng.uniform(-1, 1) * self.s.jitter))
            x += 14
        pts.append((x1, y))
        if len(pts) > 1:
            self.draw.line(pts, fill=self.s.ink_color, width=3)

    def _picture(self, image_id: str) -> Optional[Image.Image]:
        if image_id not in self._proc:
            raw = self.raw_images.get(image_id)
            self._proc[image_id] = (process_image(raw, self.s.image_mode, self.s.ink_color)
                                    if raw is not None else None)
        return self._proc[image_id]

    def picture(self, image_id: str, pct: Optional[int]):
        img = self._picture(image_id)
        if img is None:
            return
        s = self.s
        w = int(self.text_w * (pct or s.image_width_pct) / 100)
        h = int(img.height * w / img.width)
        max_h = int((self.H - self.mt - self.mb) * 0.7)
        if h > max_h:
            h, w = max_h, int(img.width * max_h / img.height)
        n = max(1, math.ceil((h + 0.25 * self.pitch) / self.pitch))  # lines it occupies
        if self.y + (n - 1) * self.pitch > self.bottom and not self.empty:
            self.new_page()
        top = self.y - self.pitch + int((n * self.pitch - h) / 2)
        x = self.ml + (self.text_w - w) // 2
        resized = img.resize((w, h), Image.LANCZOS)
        if s.image_mode in ("sketch", "ink") and s.paper_color.lower() == "#ffffff":
            # drawn styles blend into the paper (rules/grid show through the white)
            region = self.img.crop((x, top, x + w, top + h))
            self.img.paste(ImageChops.multiply(region, resized), (x, top))
        else:
            self.img.paste(resized, (x, top))
        self.y += n * self.pitch
        self.empty = False

    def finish(self) -> List[Image.Image]:
        self._emit_page()
        return self.pages


def render_pages(text: str, images: Dict[str, Image.Image], s: RenderSettings,
                 style_settings: Optional[Dict[str, RenderSettings]] = None,
                 page_sink: Optional[Callable[[Image.Image], None]] = None) -> List[Image.Image]:
    """Render pages, optionally sending each finished page to a sink immediately."""
    style_settings = style_settings or {}
    pages: List[Image.Image] = []
    section: List = []
    section_settings = s

    def render_section():
        if not section:
            return
        renderer = _Renderer(section_settings, images, page_sink)
        for block in section:
            if block.kind == "paragraph":
                renderer.paragraph(block.lines)
            elif block.kind == "heading":
                renderer.heading(block.lines[0])
            elif block.kind == "image":
                renderer.picture(block.image_id, block.width_pct)
            elif block.kind == "pagebreak" and not renderer.empty:
                renderer.new_page()
        rendered = renderer.finish()
        if page_sink is None:
            pages.extend(rendered)

    for block in parse_markup(_normalize(text)):
        if block.kind == "style":
            render_section()
            section = []
            section_settings = style_settings.get(block.image_id, s)
        else:
            section.append(block)
    render_section()
    return pages
