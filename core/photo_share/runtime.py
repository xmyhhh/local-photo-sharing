from __future__ import annotations

import sys
import os
from pathlib import Path


def get_app_base_dir() -> Path:
    override = os.environ.get("PHOTO_SHARE_APP_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def get_resource_base_dir() -> Path:
    override = os.environ.get("PHOTO_SHARE_RESOURCE_DIR")
    if override:
        return Path(override).expanduser().resolve()
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parents[1]
