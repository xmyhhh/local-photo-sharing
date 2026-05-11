from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from flask import Flask, abort, after_this_request, jsonify, request, send_file

from ..context import AppServices, RootServices
from ..paths import join_rooted_path, normalize_rel_path, resolve_inside, to_relative
from .gallery import _root_services
from .media import move_to_trash


def register_file_routes(app: Flask, services: AppServices) -> None:
    @app.post("/api/files/folder")
    def create_folder():
        data = request.get_json(silent=True) or {}
        name = clean_name(data.get("name"))
        parent = data.get("parent", "")
        root_services, parent_path = resolve_target_folder(services, parent)
        target = unique_child_path(parent_path, name, want_dir=True)
        target.mkdir()
        root_services.folder_counts.refresh_subtree_async(parent_path)
        return jsonify({"path": join_rooted_path(root_id_for_root(services, root_services.root), to_relative(root_services.root, target))})

    @app.post("/api/files/rename")
    def rename_item():
        data = request.get_json(silent=True) or {}
        path_value = require_string(data.get("path"), "path")
        name = clean_name(data.get("name"))
        root_services, path = resolve_existing_item(services, path_value)
        target = unique_child_path(path.parent, name, want_dir=path.is_dir())
        os.replace(path, target)
        root_services.folder_counts.refresh_subtree_async(target.parent)
        return jsonify({"path": join_rooted_path(root_id_for_root(services, root_services.root), to_relative(root_services.root, target))})

    @app.post("/api/files/delete")
    def delete_items():
        data = request.get_json(silent=True) or {}
        paths = require_paths(data.get("paths"))
        deleted = []
        for path_value in paths:
            root_services, path = resolve_existing_item(services, path_value)
            if path.is_dir():
                trashed = move_folder_to_trash(path, root_services.root, root_id_for_root(services, root_services.root))
            else:
                trashed = move_to_trash(path, root_services.root, root_id_for_root(services, root_services.root))
            root_services.folder_counts.refresh_subtree_async(path.parent)
            deleted.append({"path": path_value, "trashed": str(trashed)})
        return jsonify({"deleted": deleted})

    @app.post("/api/files/copy")
    def copy_items():
        return copy_or_move_items(services, move=False)

    @app.post("/api/files/move")
    def move_items():
        return copy_or_move_items(services, move=True)

    @app.post("/api/files/download-zip")
    def download_zip():
        data = request.get_json(silent=True) or {}
        paths = require_paths(data.get("paths"))
        items = [resolve_existing_item(services, path_value) for path_value in paths]
        archive_name = "photo-share.zip" if len(items) > 1 else f"{safe_archive_stem(items[0][1].name)}.zip"
        fd, zip_path_value = tempfile.mkstemp(prefix="photo-share-", suffix=".zip")
        os.close(fd)
        zip_path = Path(zip_path_value)
        try:
            write_zip_file(zip_path, items)
        except Exception:
            if zip_path.exists():
                zip_path.unlink()
            raise

        @after_this_request
        def cleanup_zip(response):
            response.call_on_close(lambda: remove_temp_zip(zip_path))
            return response

        return send_file(
            zip_path,
            mimetype="application/zip",
            as_attachment=True,
            download_name=archive_name,
        )


def copy_or_move_items(services: AppServices, move: bool):
    data = request.get_json(silent=True) or {}
    paths = require_paths(data.get("paths"))
    root_services, dest = resolve_target_folder(services, data.get("destination", ""))
    changed = []
    for path_value in paths:
        source_services, source = resolve_existing_item(services, path_value)
        target = unique_child_path(dest, source.name, want_dir=source.is_dir())
        if move:
            if source.is_dir() and is_relative_to(dest, source):
                abort(400, "Cannot move a folder into itself.")
            shutil.move(str(source), str(target))
            source_services.folder_counts.refresh_subtree_async(source.parent)
        else:
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)
        root_services.folder_counts.refresh_subtree_async(dest)
        changed.append({"from": path_value, "to": join_rooted_path(root_id_for_root(services, root_services.root), to_relative(root_services.root, target))})
    return jsonify({"items": changed})


def resolve_target_folder(services: AppServices, value: Any) -> tuple[RootServices, Path]:
    if not value:
        root_services = _root_services(services, services.default_save_root_id)
        return root_services, services.default_save_folder
    root_id, rel = split_rooted(require_string(value, "parent"))
    root_services = _root_services(services, root_id)
    path = resolve_inside(root_services.root, rel)
    if not path.is_dir():
        abort(404)
    return root_services, path


def resolve_existing_item(services: AppServices, value: str) -> tuple[RootServices, Path]:
    root_id, rel = split_rooted(value)
    root_services = _root_services(services, root_id)
    path = resolve_inside(root_services.root, rel)
    if not path.exists() or path == root_services.root:
        abort(404)
    return root_services, path


def split_rooted(value: str) -> tuple[str, str]:
    normalized = normalize_rel_path(value)
    parts = normalized.split("/", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        abort(400, "path must include root id and relative path.")
    return parts[0], parts[1]


def require_string(value: Any, field: str) -> str:
    if not isinstance(value, str):
        abort(400, f"{field} must be a string.")
    return value


def require_paths(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        abort(400, "paths must be a non-empty array.")
    return [require_string(item, "paths[]") for item in value]


def clean_name(value: Any) -> str:
    name = require_string(value, "name").strip()
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        abort(400, "name is invalid.")
    return name


def unique_child_path(parent: Path, name: str, want_dir: bool) -> Path:
    target = parent / name
    if not target.exists():
        return target
    stem = target.stem if not want_dir else target.name
    suffix = "" if want_dir else target.suffix
    for index in range(1, 10_000):
        candidate = parent / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
    abort(409, "Too many duplicate names.")


def move_folder_to_trash(path: Path, root: Path, root_id: str) -> Path:
    rel = path.resolve().relative_to(root)
    from ..constants import TRASH_DIR

    target_dir = TRASH_DIR / root_id / rel.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    target = unique_child_path(target_dir, path.name, want_dir=True)
    shutil.move(str(path), str(target))
    return target


def write_zip_file(zip_path: Path, items: list[tuple[RootServices, Path]]) -> None:
    used_names: set[str] = set()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for root_services, item_path in items:
            base_name = unique_archive_name(item_path.name, used_names)
            if item_path.is_dir():
                for child in item_path.rglob("*"):
                    if not child.is_file():
                        continue
                    rel = child.relative_to(item_path).as_posix()
                    archive.write(child, f"{base_name}/{rel}")
            else:
                archive.write(item_path, base_name)


def unique_archive_name(name: str, used_names: set[str]) -> str:
    cleaned = name.strip().replace("\\", "_").replace("/", "_") or "item"
    candidate = cleaned
    stem = Path(cleaned).stem or cleaned
    suffix = Path(cleaned).suffix
    index = 1
    while candidate.lower() in used_names:
        index += 1
        candidate = f"{stem} ({index}){suffix}"
    used_names.add(candidate.lower())
    return candidate


def safe_archive_stem(name: str) -> str:
    return Path(unique_archive_name(name, set())).stem or "photo-share"


def remove_temp_zip(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def root_id_for_root(services: AppServices, root: Path) -> str:
    for root_id, item in services.roots.items():
        if item == root:
            return root_id
    abort(500, "root was not registered.")


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False
