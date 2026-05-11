from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import piexif
from PIL import Image


def read_embedded_rating(photo_path: Path) -> int:
    rating = read_xmp_rating(photo_path)
    if rating:
        return rating
    return read_exif_rating(photo_path)


def read_exif_rating(photo_path: Path) -> int:
    try:
        with Image.open(photo_path) as image:
            exif = image.getexif()
    except Exception:
        return 0
    rating = normalize_rating_value(exif.get(18246))
    if rating:
        return rating
    percent = exif.get(18249)
    try:
        percent_int = int(percent)
    except (TypeError, ValueError):
        return 0
    return normalize_rating_percent(percent_int)


def read_xmp_rating(photo_path: Path) -> int:
    rating = read_xmp_head_rating(photo_path)
    if rating:
        return rating
    try:
        file_size = photo_path.stat().st_size
    except OSError:
        file_size = 0
    try:
        if file_size > 128 * 1024:
            with photo_path.open("rb") as file:
                file.seek(max(0, file_size - 128 * 1024))
                tail = file.read()
            rating = parse_xmp_rating(tail)
            if rating:
                return rating
    except OSError:
        pass
    sidecar = photo_path.with_suffix(".xmp")
    if sidecar.exists():
        try:
            return parse_xmp_rating(sidecar.read_bytes())
        except OSError:
            return 0
    return 0


def read_xmp_head_rating(photo_path: Path) -> int:
    try:
        with photo_path.open("rb") as file:
            head = file.read(128 * 1024)
    except OSError:
        return 0
    return parse_xmp_rating(head)


def parse_xmp_rating(raw: bytes) -> int:
    if not raw:
        return 0
    text = raw.decode("utf-8", errors="ignore")
    patterns = (
        r"\bxmp:Rating\s*=\s*['\"]\s*(-?\d+)\s*['\"]",
        r"<\s*xmp:Rating\s*>\s*(-?\d+)\s*<\s*/\s*xmp:Rating\s*>",
        r"\brating\s*=\s*['\"]\s*(-?\d+)\s*['\"]",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return normalize_rating_value(match.group(1))
    return 0


def normalize_rating_value(value: Any) -> int:
    try:
        rating = int(value)
    except (TypeError, ValueError):
        return 0
    if rating < 1:
        return 0
    return min(rating, 5)


def normalize_rating_percent(value: int) -> int:
    if value <= 0:
        return 0
    if value <= 1:
        return 1
    if value <= 25:
        return 2
    if value <= 50:
        return 3
    if value <= 75:
        return 4
    return 5


def write_embedded_rating(photo_path: Path, rating: int) -> None:
    exif_dict = load_exif_dict(photo_path)
    zeroth = exif_dict.setdefault("0th", {})
    zeroth[18246] = int(rating)
    zeroth[18249] = rating_to_percent(rating)
    exif_bytes = piexif.dump(exif_dict)
    piexif.insert(exif_bytes, str(photo_path))


def load_exif_dict(photo_path: Path) -> dict[str, Any]:
    try:
        exif_dict = piexif.load(str(photo_path))
    except Exception:
        exif_dict = {}
    return {
        "0th": dict(exif_dict.get("0th", {})),
        "Exif": dict(exif_dict.get("Exif", {})),
        "GPS": dict(exif_dict.get("GPS", {})),
        "Interop": dict(exif_dict.get("Interop", {})),
        "1st": dict(exif_dict.get("1st", {})),
        "thumbnail": exif_dict.get("thumbnail"),
    }


def rating_to_percent(rating: int) -> int:
    if rating <= 0:
        return 0
    if rating >= 5:
        return 99
    return rating * 20
