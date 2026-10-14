"""
markup.py
The editable text format shared by the editor, the handwriting renderer
and the DOCX exporter. It is deliberately tiny so non-technical users can
learn it in one minute:

    blank line           -> new paragraph
    single line break    -> new line inside the same paragraph
    # Some heading       -> heading
    [[IMG:img_3]]        -> picture number 3 found in your pages
    [[IMG:img_3|50]]     -> same picture at 50% width
    [[PAGEBREAK]]        -> start a new page
"""
import re
from dataclasses import dataclass, field
from typing import List, Optional

IMG_RE = re.compile(r"^\[\[IMG:([A-Za-z0-9_\-]+)(?:\|(\d{1,3}))?\]\]$")
PAGEBREAK_RE = re.compile(r"^\[\[PAGEBREAK\]\]$", re.I)
STYLE_RE = re.compile(r"^\[\[STYLE:([A-Za-z0-9_\-]+)\]\]$", re.I)


@dataclass
class Block:
    kind: str  # "paragraph" | "heading" | "image" | "pagebreak"
    lines: List[str] = field(default_factory=list)
    image_id: Optional[str] = None
    width_pct: Optional[int] = None


def parse_markup(text: str) -> List[Block]:
    blocks: List[Block] = []
    current: List[str] = []

    def flush():
        if current:
            blocks.append(Block("paragraph", lines=list(current)))
            current.clear()

    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line:
            flush()
            continue
        m = STYLE_RE.match(line)
        if m:
            flush()
            blocks.append(Block("style", image_id=m.group(1)))
            continue
        m = IMG_RE.match(line)
        if m:
            flush()
            pct = int(m.group(2)) if m.group(2) else None
            blocks.append(Block("image", image_id=m.group(1),
                                width_pct=min(100, max(10, pct)) if pct else None))
            continue
        if PAGEBREAK_RE.match(line):
            flush()
            blocks.append(Block("pagebreak"))
            continue
        if line.startswith("# "):
            flush()
            blocks.append(Block("heading", lines=[line[2:].strip()]))
            continue
        current.append(line)
    flush()
    return blocks


def strip_markup(text: str) -> str:
    """Plain text with all markers removed (used for 'Copy text')."""
    out = []
    for b in parse_markup(text):
        if b.kind in ("paragraph", "heading"):
            out.append("\n".join(b.lines))
    return "\n\n".join(out)


def image_ids(text: str) -> List[str]:
    return [b.image_id for b in parse_markup(text) if b.kind == "image"]


def reflow(text: str) -> str:
    """Join hard-wrapped lines (from OCR / PDF blocks) into one paragraph
    line, repairing words split by a line-end hyphen."""
    text = re.sub(r"([a-z])-\n([a-z])", r"\1\2", text)
    text = re.sub(r"\s*\n\s*", " ", text)
    return re.sub(r"[ \t]+", " ", text).strip()
