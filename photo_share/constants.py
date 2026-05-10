from __future__ import annotations

import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = APP_DIR / "static"
JPG_EXTENSIONS = {".jpg", ".jpeg"}
RATINGS_FILE = ".photo_share_ratings.json"
THUMBNAIL_DIR = ".photo_share_thumbs"
CACHE_DIR = APP_DIR / ".photo_share_cache"
CPU_COUNT = os.cpu_count() or 1
THUMBNAIL_WORKERS = min(8, max(2, CPU_COUNT))
METADATA_WORKERS = min(4, max(2, CPU_COUNT // 2))
THUMB_CACHE_QUEUE_LIMIT = 50
PREVIEW_CACHE_QUEUE_LIMIT = 25
FILTER_WAIT_SECONDS = 0.8
PHOTO_PAGE_SIZE = 80
DEFAULT_THUMBNAIL_SIZE = 360
DEFAULT_THUMBNAIL_QUALITY = 74
DEFAULT_PREVIEW_SIZE = 2560
DEFAULT_PREVIEW_QUALITY = 88
THUMBNAIL_MODES = {
    "small": {"size": 260, "quality": 68},
    "medium": {"size": DEFAULT_THUMBNAIL_SIZE, "quality": DEFAULT_THUMBNAIL_QUALITY},
    "large": {"size": 640, "quality": 84},
}
DEFAULT_THUMBNAIL_MODE = "medium"
BRACKET_SCAN_LIMIT = 500
DEFAULT_CONFIG_FILE = APP_DIR / "config.json"
DEFAULT_CONFIG = {
    "photo_folder": "D:/your/photo/folder",
    "host": "0.0.0.0",
    "port": 8000,
    "thumbnail_size": DEFAULT_THUMBNAIL_SIZE,
    "thumbnail_quality": DEFAULT_THUMBNAIL_QUALITY,
    "preview_size": DEFAULT_PREVIEW_SIZE,
    "preview_quality": DEFAULT_PREVIEW_QUALITY,
}
