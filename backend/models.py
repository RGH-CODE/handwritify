"""
models.py
Small shared types. A converted document is an ordered list of items:
text blocks and pictures (figures cropped out of the source pages).
"""
from dataclasses import dataclass
from typing import Union

from PIL import Image


@dataclass
class TextItem:
    text: str


@dataclass
class ImageItem:
    image: Image.Image


Item = Union[TextItem, ImageItem]


def flatten_rgb(img: Image.Image) -> Image.Image:
    """Convert any PIL image to RGB, putting transparent areas on white
    (a plain .convert('RGB') turns transparency black)."""
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, "white")
        bg.paste(rgba, mask=rgba.getchannel("A"))
        return bg
    return img.convert("RGB")
