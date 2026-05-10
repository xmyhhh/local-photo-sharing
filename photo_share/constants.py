from __future__ import annotations

import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = APP_DIR / "static"
JPG_EXTENSIONS = {".jpg", ".jpeg"}
PHOTO_EXTENSIONS = JPG_EXTENSIONS | {".heic", ".heif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm"}
LIVE_VIDEO_EXTENSIONS = {".mov", ".m4v"}
MEDIA_EXTENSIONS = PHOTO_EXTENSIONS | VIDEO_EXTENSIONS
RATINGS_FILE = ".photo_share_ratings.json"
THUMBNAIL_DIR = ".photo_share_thumbs"
CACHE_DIR = APP_DIR / ".photo_share_cache"
TRASH_DIR = APP_DIR / ".photo_share_trash"
BRACKET_OUTPUT_DIR = APP_DIR / ".photo_share_bracket_results"
BRACKET_CACHE_FILE = CACHE_DIR / "bracket_detection_cache.json"
DEFAULT_BRACKET_PROJECT_FILE = APP_DIR / "bracket_project.prj"
CPU_COUNT = os.cpu_count() or 1
THUMBNAIL_WORKERS = min(16, max(2, CPU_COUNT))
METADATA_WORKERS = min(4, max(2, CPU_COUNT // 2))
BRACKET_FEATURE_WORKERS = min(16, max(2, CPU_COUNT))
BRACKET_MERGE_WORKERS = min(4, max(1, CPU_COUNT // 2))
PREVIEW_CACHE_QUEUE_LIMIT = 25
FILTER_WAIT_SECONDS = 0.8
DEFAULT_ENTRY_PLACEHOLDER_LIMIT = 2000
DEFAULT_PREVIEW_SIZE = 2560
DEFAULT_PREVIEW_QUALITY = 88
THUMBNAIL_MODES = {
    "small": {"size": 180, "quality": 58, "queue_limit": 100},
    "medium": {"size": 300, "quality": 66, "queue_limit": 70},
    "large": {"size": 520, "quality": 76, "queue_limit": 40},
    "xlarge": {"size": 1280, "quality": 92, "queue_limit": 30},
}
DEFAULT_THUMBNAIL_MODE = "medium"
BRACKET_SCAN_LIMIT = 500
DEFAULT_CONFIG_FILE = APP_DIR / "config.json"
DEFAULT_CONFIG = {
    "photo_folders": ["D:/your/photo/folder"],
    "host": "0.0.0.0",
    "port": 8000,
    "thumbnail_modes": {
        mode: {
            "size": int(spec["size"]),
            "quality": int(spec["quality"]),
        }
        for mode, spec in THUMBNAIL_MODES.items()
    },
    "thumbnail_queue_limits": {
        "small": 100,
        "medium": 70,
        "large": 40,
        "xlarge": 30,
    },
    "preview_size": DEFAULT_PREVIEW_SIZE,
    "preview_quality": DEFAULT_PREVIEW_QUALITY,
    "upload_password": "",
}
