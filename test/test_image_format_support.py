from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from core.photo_share.constants import (
    BROWSER_RENDERABLE_PHOTO_EXTENSIONS,
    HDR_EXTENSIONS,
    MEDIA_EXTENSIONS,
    PHOTO_EXTENSIONS,
    PNG_EXTENSIONS,
)
from core.photo_share.image_cache import ImageCacheStore
from core.photo_share.image_decode import load_photo_image


def write_hdr_sample(path: Path) -> Path:
    import cv2

    data = np.array(
        [
            [[0.12, 0.25, 0.5], [0.8, 0.45, 0.22]],
            [[1.6, 1.1, 0.7], [3.2, 2.0, 1.2]],
        ],
        dtype=np.float32,
    )
    if not cv2.imwrite(str(path), data):
        raise AssertionError(f"failed to write HDR sample: {path}")
    return path


def test_png_and_hdr_are_supported_photo_formats() -> None:
    assert PNG_EXTENSIONS <= PHOTO_EXTENSIONS
    assert HDR_EXTENSIONS <= PHOTO_EXTENSIONS
    assert PNG_EXTENSIONS <= MEDIA_EXTENSIONS
    assert HDR_EXTENSIONS <= MEDIA_EXTENSIONS
    assert PNG_EXTENSIONS <= BROWSER_RENDERABLE_PHOTO_EXTENSIONS
    assert not HDR_EXTENSIONS & BROWSER_RENDERABLE_PHOTO_EXTENSIONS


def test_hdr_sample_can_be_decoded_for_preview(tmp_path: Path) -> None:
    sample = write_hdr_sample(tmp_path / "sample.hdr")

    image = load_photo_image(sample)

    assert image.mode == "RGB"
    assert image.width > 0
    assert image.height > 0


def test_png_and_hdr_thumbnail_generation(tmp_path: Path) -> None:
    png = tmp_path / "sample.png"
    Image.new("RGBA", (16, 12), (255, 0, 0, 128)).save(png)
    hdr = write_hdr_sample(tmp_path / "sample.hdr")
    store = ImageCacheStore(
        root=tmp_path,
        cache_root=tmp_path / ".thumbs",
        size=64,
        quality=70,
        thread_name="test-thumb",
    )

    store.warmup_one(png)
    store._generate(hdr, "sample.hdr")

    assert store.get_ready(png, validate=True) is not None
    assert store.cache_path_for_rel("sample.hdr").is_file()
