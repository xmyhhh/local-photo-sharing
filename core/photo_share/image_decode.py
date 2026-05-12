from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from .constants import HDR_EXTENSIONS


def load_photo_image(path: Path) -> Image.Image:
    if path.suffix.lower() in HDR_EXTENSIONS:
        return load_hdr_image(path)
    with Image.open(path) as image:
        prepared = ImageOps.exif_transpose(image)
        prepared.load()
        return prepared


def load_hdr_image(path: Path) -> Image.Image:
    import cv2

    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise OSError(f"cannot identify image file {path}")
    if image.ndim == 2:
        rgb = image.astype(np.float32)
    else:
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB).astype(np.float32)
    rgb = np.nan_to_num(rgb, nan=0.0, posinf=0.0, neginf=0.0)
    rgb = np.maximum(rgb, 0.0)
    scale = float(np.percentile(rgb, 99.0)) if rgb.size else 1.0
    scale = max(scale, 1e-6)
    mapped = rgb / scale
    mapped = mapped / (1.0 + mapped)
    mapped = np.power(np.clip(mapped, 0.0, 1.0), 1.0 / 2.2)
    output = (mapped * 255.0 + 0.5).astype(np.uint8)
    return Image.fromarray(output, mode="RGB")
