from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from .constants import (
    DEFAULT_CONFIG,
    DEFAULT_CONFIG_FILE,
    THUMBNAIL_MODES,
)
from .memory_prefetch import MemoryPrefetchSettings, system_prefetch_memory_limit_mb


def build_default_config(photo_root: Path | str | None = None) -> dict[str, Any]:
    config = copy.deepcopy(DEFAULT_CONFIG)
    if photo_root is not None:
        root_text = str(Path(photo_root).expanduser())
        config["photo_folders"] = [root_text]
        config["default_save_folder"] = root_text
    return config


def create_default_config(config_path: Path, photo_root: Path | str | None = None) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(build_default_config(photo_root), ensure_ascii=False, indent=2), encoding="utf-8")


def write_config(config_path: Path | None, config: dict[str, Any]) -> None:
    if config_path is None:
        return
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def load_config(config_path: Path) -> dict[str, Any] | None:
    if not config_path.exists():
        create_default_config(config_path)
        print(f"Config file was not found. Created default config: {config_path}")
        print("Edit photo_folders/default_save_folder in the config file, then start the app again.")
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
        raise ValueError("Config field photo_folders must be a non-empty array of strings.")
    if not isinstance(value, list) or not value:
        raise ValueError("Config field photo_folders must be a non-empty array of strings.")
    folders: list[Path] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("Config field photo_folders must contain only non-empty strings.")
        folders.append(Path(item).expanduser())
    return folders


def get_default_save_folder(config: dict[str, Any]) -> Path:
    value = config.get("default_save_folder")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Config field default_save_folder must be a non-empty string.")
    return Path(value).expanduser()


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


def get_thumbnail_mode_settings(config: dict[str, Any]) -> dict[str, dict[str, int]]:
    defaults = {
        mode: {
            "size": int(spec["size"]),
            "quality": int(spec["quality"]),
            "queue_limit": int(spec["queue_limit"]),
        }
        for mode, spec in THUMBNAIL_MODES.items()
    }
    value = config.get("thumbnail_modes", {})
    if value is None:
        return defaults
    if not isinstance(value, dict):
        raise ValueError("Config field thumbnail_modes must be an object.")

    settings = {mode: spec.copy() for mode, spec in defaults.items()}
    for mode in defaults:
        if mode not in value:
            continue
        item = value[mode]
        if not isinstance(item, dict):
            raise ValueError(f"Config field thumbnail_modes.{mode} must be an object.")
        if "size" in item:
            settings[mode]["size"] = _parse_int_range(
                item["size"],
                f"thumbnail_modes.{mode}.size",
                120,
                2400,
            )
        if "quality" in item:
            settings[mode]["quality"] = _parse_int_range(
                item["quality"],
                f"thumbnail_modes.{mode}.quality",
                40,
                92,
            )
        if "queue_limit" in item:
            settings[mode]["queue_limit"] = _parse_int_range(
                item["queue_limit"],
                f"thumbnail_modes.{mode}.queue_limit",
                10,
                1000,
            )
    return settings


def _parse_int_range(value: Any, field: str, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Config field {field} must be an integer.") from exc
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"Config field {field} must be between {minimum} and {maximum}.")
    return parsed


def get_memory_prefetch_settings(config: dict[str, Any]) -> MemoryPrefetchSettings:
    value = config.get("memory_prefetch", DEFAULT_CONFIG["memory_prefetch"])
    if not isinstance(value, dict):
        raise ValueError("Config field memory_prefetch must be an object.")
    return MemoryPrefetchSettings(
        enabled=bool(value.get("enabled", False)),
        memory_limit_mb=_parse_int_range(
            value.get("memory_limit_mb", 1024),
            "memory_prefetch.memory_limit_mb",
            256,
            system_prefetch_memory_limit_mb(),
        ),
    )


def get_upload_password(config: dict[str, Any]) -> str:
    value = config.get("upload_password", DEFAULT_CONFIG["upload_password"])
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("Config field upload_password must be a string.")
    return value


def get_auth_config(config: dict[str, Any]) -> dict[str, Any]:
    value = config.get("auth", DEFAULT_CONFIG["auth"])
    if value is None:
        return dict(DEFAULT_CONFIG["auth"])
    if not isinstance(value, dict):
        raise ValueError("Config field auth must be an object.")
    result = dict(DEFAULT_CONFIG["auth"])
    result.update(value)
    for field in ("password", "session_secret"):
        if result.get(field) is None:
            result[field] = ""
        if not isinstance(result.get(field), str):
            raise ValueError(f"Config field auth.{field} must be a string.")
    for field in ("login_background_mode", "login_background_folder", "login_background_layout"):
        if result.get(field) is None:
            result[field] = ""
        if not isinstance(result.get(field), str):
            raise ValueError(f"Config field auth.{field} must be a string.")
    for field in ("public_albums", "login_backgrounds"):
        items = result.get(field, [])
        if items is None:
            items = []
        if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
            raise ValueError(f"Config field auth.{field} must be an array of strings.")
        result[field] = items
    result["enabled"] = bool(result.get("enabled", False))
    if result["login_background_mode"] not in {"none", "rated", "folder"}:
        result["login_background_mode"] = "none"
    if result["login_background_layout"] not in {"grid", "stack", "solo"}:
        result["login_background_layout"] = "grid"
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Share a local JPG folder on your LAN.")
    parser.add_argument("mode", nargs="?", choices=("serve", "warmup"), default="serve", help="Startup mode. Use warmup to build all thumbnail caches before serving.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_FILE), help="JSON config file path. Default: config.json in the project runtime directory")
    return parser.parse_args()
