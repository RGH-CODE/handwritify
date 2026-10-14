"""
schemas.py
Every look/spacing/format option in one validated place. The frontend sends
this as JSON; anything out of range is rejected with a readable error.
"""
from typing import Literal

from pydantic import BaseModel, Field


class RenderSettings(BaseModel):
    style: str = ""                                   # font file name (no extension)
    paper: Literal["ruled", "grid", "blank"] = "ruled"
    paper_color: str = Field("#ffffff", pattern=r"^#[0-9a-fA-F]{6}$")
    ink_color: str = Field("#1a2b6d", pattern=r"^#[0-9a-fA-F]{6}$")
    font_size: int = Field(42, ge=20, le=90)          # px at 200 dpi
    jitter: float = Field(1.0, ge=0, le=2)            # natural variation

    # spacing
    line_spacing: float = Field(1.5, ge=1.0, le=3.0)  # x font size
    word_spacing: float = Field(1.0, ge=0.5, le=3.0)  # x normal space
    letter_spacing: float = Field(0.0, ge=-3, le=10)  # extra px per letter
    paragraph_gap: float = Field(0.5, ge=0, le=4)     # in lines
    first_line_indent_mm: float = Field(0, ge=0, le=40)

    # page
    page_size: Literal["a4", "a5", "letter", "canvas"] = "a4"
    margin_top_mm: float = Field(18, ge=5, le=60)
    margin_bottom_mm: float = Field(18, ge=5, le=60)
    margin_left_mm: float = Field(22, ge=5, le=60)
    margin_right_mm: float = Field(15, ge=5, le=60)
    align: Literal["left", "center", "right", "justify"] = "left"
    heading_scale: float = Field(1.4, ge=1.0, le=2.5)
    page_numbers: bool = False

    # pictures found in the source pages
    image_mode: Literal["sketch", "original", "grayscale", "ink", "skip"] = "sketch"
    image_width_pct: int = Field(70, ge=20, le=100)

    seed: int = 12345                                 # same seed = same "hand"
