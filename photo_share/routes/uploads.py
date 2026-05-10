from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlencode

from flask import Flask, abort, jsonify, redirect, request

from ..constants import PHOTO_EXTENSIONS, MEDIA_EXTENSIONS
from ..context import AppServices
from ..live_photos import find_live_video
from ..paths import join_rooted_path, normalize_rel_path, to_relative

WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def register_upload_routes(app: Flask, services: AppServices) -> None:
    @app.post("/api/upload-folder")
    def create_upload_folder():
        payload = request.get_json(silent=True) or {}
        folder = str(payload.get("folder", "")).strip()
        try:
            target = _resolve_upload_folder(services, folder, create=True)
        except ValueError as exc:
            return jsonify({"message": str(exc)}), 400
        root = services.roots[services.default_root_id]
        rel = to_relative(root, target) if target != root else ""
        return jsonify({
            "root": services.default_root_id,
            "folder": rel,
            "path": join_rooted_path(services.default_root_id, rel),
        })

    @app.post("/api/upload")
    def upload_files():
        folder = request.form.get("folder", "").strip()
        result, status = save_uploaded_files(services, folder)
        return jsonify(result), status

    @app.post("/share-target")
    def receive_shared_files():
        folder = request.form.get("folder", "").strip() or "Shared from iPhone"
        result, _status = save_uploaded_files(services, folder)
        rel = result.get("folder", "")
        return redirect(f"/?{urlencode({'shared': '1', 'folder': rel})}", code=303)


def save_uploaded_files(services: AppServices, folder: str) -> tuple[dict, int]:
    try:
        target = _resolve_upload_folder(services, folder, create=True)
    except ValueError as exc:
        return {"message": str(exc)}, 400
    root = services.roots[services.default_root_id]
    files = request.files.getlist("files")
    if not files:
        return {"message": "No files were uploaded."}, 400

    saved: list[dict[str, str | int]] = []
    saved_paths: list[Path] = []
    rejected: list[dict[str, str]] = []
    for storage in files:
        original_name = storage.filename or ""
        filename = sanitize_upload_filename(original_name)
        if not filename:
            rejected.append({"name": original_name, "reason": "Invalid file name."})
            continue
        suffix = Path(filename).suffix.lower()
        if suffix not in MEDIA_EXTENSIONS:
            rejected.append({"name": original_name, "reason": "Unsupported file type."})
            continue
        destination = unique_destination(target, filename)
        storage.save(destination)
        saved_paths.append(destination)
        saved.append({
            "name": destination.name,
            "path": join_rooted_path(services.default_root_id, to_relative(root, destination)),
            "size": destination.stat().st_size,
        })

    rel = to_relative(root, target) if target != root else ""
    unpaired_live_candidates = [
        {
            "name": path.name,
            "path": join_rooted_path(services.default_root_id, to_relative(root, path)),
        }
        for path in saved_paths
        if path.suffix.lower() in PHOTO_EXTENSIONS and find_live_video(path) is None
    ]
    return {
        "root": services.default_root_id,
        "folder": rel,
        "saved": saved,
        "rejected": rejected,
        "unpairedLiveCandidates": unpaired_live_candidates,
    }, 200


def _resolve_upload_folder(services: AppServices, folder: str, create: bool = False) -> Path:
    root = services.roots[services.default_root_id]
    rel = sanitize_upload_folder(folder)
    target = (root / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        abort(403)
    if create:
        target.mkdir(parents=True, exist_ok=True)
    if not target.is_dir():
        abort(404)
    return target


def sanitize_upload_folder(folder: str) -> str:
    normalized = normalize_rel_path(folder)
    if not normalized:
        return ""
    parts: list[str] = []
    for raw_part in normalized.split("/"):
        part = sanitize_folder_part(raw_part)
        if not part:
            raise ValueError("Invalid folder name.")
        parts.append(part)
    return "/".join(parts)


def sanitize_folder_part(part: str) -> str:
    name = part.strip().strip(".")
    name = re.sub(r"[\x00-\x1f<>:\"/\\|?*]+", "_", name)
    name = re.sub(r"\s+", " ", name).strip().strip(".")
    if not name:
        return ""
    if name.upper() in WINDOWS_RESERVED_NAMES:
        name = f"_{name}"
    return name


def sanitize_upload_filename(filename: str) -> str:
    name = Path(filename.replace("\\", "/")).name.strip().strip(".")
    if not name:
        return ""
    stem = Path(name).stem
    suffix = Path(name).suffix
    if not suffix:
        return ""
    stem = sanitize_folder_part(stem)
    if not stem:
        return ""
    if stem.upper() in WINDOWS_RESERVED_NAMES:
        stem = f"_{stem}"
    return f"{stem}{suffix}"


def unique_destination(folder: Path, filename: str) -> Path:
    candidate = folder / filename
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    for index in range(1, 10_000):
        candidate = folder / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
    abort(409, "Too many duplicate file names.")
