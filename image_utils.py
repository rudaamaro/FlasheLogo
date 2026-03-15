from pathlib import Path
from typing import Tuple

from PIL import Image
from PyQt5.QtCore import QSize
from PyQt5.QtGui import QImage, QPixmap


def load_image(path: Path) -> Image.Image:
    return Image.open(path).convert("RGBA")


def compute_logo_size(
    base_size: Tuple[int, int],
    logo_size: Tuple[int, int],
    scale_percent: int,
    margin_percent: int,
) -> Tuple[int, int, int]:
    base_w, base_h = base_size
    logo_w, logo_h = logo_size
    shortest = min(base_w, base_h)
    margin_px = int(shortest * margin_percent / 100)
    target_w = int(shortest * scale_percent / 100)

    max_w = max(base_w - 2 * margin_px, 1)
    max_h = max(base_h - 2 * margin_px, 1)

    ratio = min(target_w / logo_w, max_w / logo_w, max_h / logo_h)
    new_w = max(1, int(logo_w * ratio))
    new_h = max(1, int(logo_h * ratio))
    return new_w, new_h, margin_px


def place_logo(
    base: Image.Image,
    logo: Image.Image,
    scale_percent: int,
    margin_percent: int,
    position: str,
) -> Image.Image:
    canvas = base.convert("RGBA")
    new_w, new_h, margin_px = compute_logo_size(canvas.size, logo.size, scale_percent, margin_percent)
    resized_logo = logo.resize((new_w, new_h), Image.LANCZOS)

    base_w, base_h = canvas.size
    positions = {
        "Canto superior esquerdo": (margin_px, margin_px),
        "Centro superior": ((base_w - new_w) // 2, margin_px),
        "Canto superior direito": (base_w - new_w - margin_px, margin_px),
        "Centro": ((base_w - new_w) // 2, (base_h - new_h) // 2),
        "Canto inferior esquerdo": (margin_px, base_h - new_h - margin_px),
        "Centro inferior": ((base_w - new_w) // 2, base_h - new_h - margin_px),
        "Canto inferior direito": (base_w - new_w - margin_px, base_h - new_h - margin_px),
    }
    pos = positions.get(position, positions["Canto inferior direito"])
    pos = (max(0, pos[0]), max(0, pos[1]))
    canvas.paste(resized_logo, pos, resized_logo)
    return canvas


def pil_to_qpixmap(img: Image.Image, max_size: QSize) -> QPixmap:
    preview_img = img.copy()
    preview_img.thumbnail((max_size.width(), max_size.height()), Image.LANCZOS)
    data = preview_img.tobytes("raw", "RGBA")
    qimg = QImage(data, preview_img.width, preview_img.height, QImage.Format_RGBA8888)
    return QPixmap.fromImage(qimg)
