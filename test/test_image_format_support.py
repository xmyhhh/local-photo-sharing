from __future__ import annotations

from pathlib import Path

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


HDR_SAMPLE_DIR = Path(r"C:\Users\xmyci\Desktop\Enjon\Assets\Textures\HDR")


def test_png_and_hdr_are_supported_photo_formats() -> None:
    assert PNG_EXTENSIONS <= PHOTO_EXTENSIONS
    assert HDR_EXTENSIONS <= PHOTO_EXTENSIONS
    assert PNG_EXTENSIONS <= MEDIA_EXTENSIONS
    assert HDR_EXTENSIONS <= MEDIA_EXTENSIONS
    assert PNG_EXTENSIONS <= BROWSER_RENDERABLE_PHOTO_EXTENSIONS
    assert not HDR_EXTENSIONS & BROWSER_RENDERABLE_PHOTO_EXTENSIONS


def test_hdr_sample_can_be_decoded_for_preview() -> None:
    sample = next(HDR_SAMPLE_DIR.glob("*.hdr"))

    image = load_photo_image(sample)

    assert image.mode == "RGB"
    assert image.width > 0
    assert image.height > 0


def test_png_and_hdr_thumbnail_generation(tmp_path: Path) -> None:
    png = tmp_path / "sample.png"
    Image.new("RGBA", (16, 12), (255, 0, 0, 128)).save(png)
    hdr = next(HDR_SAMPLE_DIR.glob("*.hdr"))
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
