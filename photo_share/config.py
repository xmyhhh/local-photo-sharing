from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .constants import (
    DEFAULT_CONFIG,
    DEFAULT_CONFIG_FILE,
    DEFAULT_PREVIEW_QUALITY,
    DEFAULT_PREVIEW_SIZE,
    DEFAULT_THUMBNAIL_QUALITY,
    DEFAULT_THUMBNAIL_SIZE,
)


def create_default_config(config_path: Path) -> None:
    config_path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")


def load_config(config_path: Path) -> dict[str, Any] | None:
    if not config_path.exists():
        create_default_config(config_path)
        print(f"Config file was not found. Created default config: {config_path}")
        print("Edit photo_folder in the config file, then start the app again.")
        return None
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON config: {config_path} ({exc})") from exc
    if not isinstance(config, dict):
        raise ValueError("Config root must be a JSON object.")
    return config


def get_config_path(value: str | None) -> Path:
    if not value:
        return DEFAULT_CONFIG_FILE
    return Path(value).expanduser().resolve()


def get_photo_folders(config: dict[str, Any]) -> list[Path]:
    value = config.get("photo_folders")
    if value is None:
        legacy = config.get("photo_folder")
        if isinstance(legacy, str) and legacy.strip():
            return [Path(legacy).expanduser()]
        raise ValueError("Config field photo_folders must be a non-empty array of strings.")
    if not isinstance(value, list) or not value:
        raise ValueError("Config field photo_folders must be a non-empty array of strings.")
    folders: list[Path] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("Config field photo_folders must contain only non-empty strings.")
        folders.append(Path(item).expanduser())
    return folders


def get_host(config: dict[str, Any]) -> str:
    value = config.get("host", DEFAULT_CONFIG["host"])
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Config field host must be a non-empty string.")
    return value


def get_port(config: dict[str, Any]) -> int:
    value = config.get("port", DEFAULT_CONFIG["port"])
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Config field port must be an integer.") from exc
    if port < 1 or port > 65535:
        raise ValueError("Config field port must be between 1 and 65535.")
    return port


def get_thumbnail_size(config: dict[str, Any]) -> int:
    value = config.get("thumbnail_size", DEFAULT_THUMBNAIL_SIZE)
    try:
        size = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Config field thumbnail_size must be an integer.") from exc
    if size < 160 or size > 1200:
        raise ValueError("Config field thumbnail_size must be between 160 and 1200.")
    return size


def get_thumbnail_quality(config: dict[str, Any]) -> int:
    value = config.get("thumbnail_quality", DEFAULT_THUMBNAIL_QUALITY)
    try:
        quality = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Config field thumbnail_quality must be an integer.") from exc
    if quality < 40 or quality > 92:
        raise ValueError("Config field thumbnail_quality must be between 40 and 92.")
    return quality


def get_preview_size(config: dict[str, Any]) -> int:
    value = config.get("preview_size", DEFAULT_PREVIEW_SIZE)
    try:
        size = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Config field preview_size must be an integer.") from exc
    if size < 800 or size > 4000:
        raise ValueError("Config field preview_size must be between 800 and 4000.")
    return size


def get_preview_quality(config: dict[str, Any]) -> int:
    value = config.get("preview_quality", DEFAULT_PREVIEW_QUALITY)
    try:
        quality = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Config field preview_quality must be an integer.") from exc
    if quality < 50 or quality > 95:
        raise ValueError("Config field preview_quality must be between 50 and 95.")
    return quality


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Share a local JPG folder on your LAN.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_FILE), help="JSON config file path. Default: config.json next to app.py")
    return parser.parse_args()
