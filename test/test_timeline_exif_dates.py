from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import piexif
from PIL import Image

from plugins.timeline.plugin import build_timeline_entry, photo_taken_timestamp


class _EmptyRatings:
    def get_override(self, rel: str) -> int | None:
        return None


class _Metadata:
    def __init__(self) -> None:
        self.ready: dict[str, int] = {}

    def is_ready(self, photo_path: Path) -> bool:
        return False

    def get_rating_ready(self, photo_path: Path) -> int:
        return self.ready.get(photo_path.name, 0)

    def set_ready(self, photo_path: Path, rating: int) -> None:
        self.ready[photo_path.name] = rating


class _RatingIndex:
    def __init__(self, rating: int) -> None:
        self.rating = rating

    def get(self, rel: str) -> int | None:
        return None

    def ensure_photo(self, photo_path: Path) -> int:
        return self.rating


class _RootServices:
    def __init__(self, root: Path, rating: int) -> None:
        self.root = root
        self.ratings = _EmptyRatings()
        self.metadata = _Metadata()
        self.rating_index = _RatingIndex(rating)


def test_photo_taken_timestamp_prefers_exif_datetime_original(tmp_path: Path) -> None:
    photo = tmp_path / "photo.jpg"
    Image.new("RGB", (2, 2), "white").save(photo)
    exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2025:10:25 00:00:00"}}
    piexif.insert(piexif.dump(exif), str(photo))
    os.utime(photo, (1_700_000_000, 1_700_000_000))

    assert photo_taken_timestamp(photo, photo.stat()) == int(datetime(2025, 10, 25).timestamp())


def test_photo_taken_timestamp_falls_back_to_file_mtime(tmp_path: Path) -> None:
    photo = tmp_path / "photo.jpg"
    Image.new("RGB", (2, 2), "white").save(photo)
    os.utime(photo, (1_700_000_000, 1_700_000_000))

    assert photo_taken_timestamp(photo, photo.stat()) == 1_700_000_000


def test_build_timeline_entry_uses_full_embedded_rating(tmp_path: Path) -> None:
    photo = tmp_path / "rated.jpg"
    Image.new("RGB", (2, 2), "white").save(photo)

    entry = build_timeline_entry("main", _RootServices(tmp_path, 4), photo, photo.stat())

    assert entry is not None
    assert entry.rating == 4
