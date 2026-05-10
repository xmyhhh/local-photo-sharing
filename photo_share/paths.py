from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from flask import abort, send_file

from .constants import DEFAULT_THUMBNAIL_MODE, JPG_EXTENSIONS, RATINGS_FILE, THUMBNAIL_DIR, THUMBNAIL_MODES


def resolve_folder(root: Path, rel_path: str) -> Path:
    path = resolve_inside(root, rel_path)
    if not path.is_dir():
        abort(404)
    return path


def resolve_photo(root: Path, rel_path: str) -> Path:
    path = resolve_inside(root, rel_path)
    if not path.is_file() or path.suffix.lower() not in JPG_EXTENSIONS:
        abort(404)
    return path


def resolve_inside(root: Path, rel_path: str) -> Path:
    normalized = normalize_rel_path(rel_path)
    path = (root / normalized).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        abort(403)
    return path


def normalize_rel_path(path: str) -> str:
    normalized = Path(path.replace("\\", "/"))
    if normalized.is_absolute() or ".." in normalized.parts:
        abort(403)
    result = as_posix(normalized)
    return "" if result == "." else result


def to_relative(root: Path, path: Path) -> str:
    return as_posix(path.resolve().relative_to(root))


def as_posix(path: Path) -> str:
    return path.as_posix()


def send_cached_file(path: Path, **kwargs: Any) -> Any:
    response = send_file(path, conditional=True, max_age=31536000, etag=True, **kwargs)
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


def parse_rooted_path(value: str) -> tuple[str, str]:
    normalized = normalize_rel_path(value)
    if not normalized:
        abort(403)
    parts = normalized.split("/", 1)
    root_id = parts[0]
    rel_path = parts[1] if len(parts) > 1 else ""
    return root_id, rel_path


def join_rooted_path(root_id: str, rel_path: str = "") -> str:
    if not rel_path:
        return root_id
    return f"{root_id}/{normalize_rel_path(rel_path)}"


def thumb_url(photo_path: str, mode: str = DEFAULT_THUMBNAIL_MODE) -> str:
    safe_mode = get_thumbnail_mode(mode)
    return f"/api/thumb/{quote_path(normalize_rel_path(photo_path))}?mode={safe_mode}"


def preview_url(photo_path: str) -> str:
    return f"/api/preview/{quote_path(normalize_rel_path(photo_path))}"


def image_url(photo_path: str) -> str:
    return f"/api/image/{quote_path(normalize_rel_path(photo_path))}"


def iter_folder_children(folder_path: Path):
    dirs: list[Path] = []
    photos: list[Path] = []
    with os.scandir(folder_path) as items:
        for item in items:
            if item.name in {RATINGS_FILE, THUMBNAIL_DIR}:
                continue
            try:
                if item.is_dir():
                    dirs.append(Path(item.path))
                elif item.is_file() and Path(item.name).suffix.lower() in JPG_EXTENSIONS:
                    photos.append(Path(item.path))
            except OSError:
                continue
    dirs.sort(key=lambda p: p.name.lower())
    photos.sort(key=lambda p: p.name.lower())
    yield from dirs
    yield from photos


def quote_path(path: str) -> str:
    from urllib.parse import quote
    return "/".join(quote(part) for part in path.split("/"))


def root_cache_key(root: Path) -> str:
    return hash_text(str(root).lower())


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_thumbnail_modes(base_size: int, base_quality: int) -> dict[str, dict[str, int]]:
    modes = {mode: spec.copy() for mode, spec in THUMBNAIL_MODES.items()}
    modes[DEFAULT_THUMBNAIL_MODE] = {
        **modes[DEFAULT_THUMBNAIL_MODE],
        "size": base_size,
        "quality": base_quality,
    }
    return modes


def get_thumbnail_mode(value: str | None) -> str:
    if not value:
        return DEFAULT_THUMBNAIL_MODE
    if value not in THUMBNAIL_MODES:
        abort(400, "thumbnail mode must be small, medium, large, or xlarge.")
    return value
