from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from flask import Flask, abort, jsonify, request

from core.photo_share.constants import PHOTO_EXTENSIONS
from core.photo_share.context import AppServices
from core.photo_share.delete_service import cleanup_photo_indexes, delete_path
from core.photo_share.paths import join_rooted_path, resolve_folder, resolve_media, thumb_url, to_relative
from core.photo_share.routes.gallery import _root_services

PLUGIN = {
    "title": "重复照片检查",
    "description": "递归扫描并清理 MD5 完全一致的重复照片。",
    "static_dir": "static",
    "scripts": ["duplicate_checker.js"],
    "styles": ["duplicate_checker.css"],
    "components": [
        {
            "id": "duplicate_checker.scan_folder",
            "title": "检查重复照片",
            "description": "递归扫描一个或多个文件夹中 MD5 完全一致的照片，并根据保留策略生成删除清单。",
            "capabilities": [
                {
                    "type": "folder_batch",
                    "recursive": True,
                    "multi": True,
                    "operations": ["scan", "plan_delete", "delete_duplicates", "cleanup_empty_folders"],
                }
            ],
            "triggers": [
                {"type": "context_menu", "target": "folder", "label": "检查重复照片", "icon": "≡", "action": "duplicate_checker.scan_folder"},
            ],
            "surfaces": [
                {"type": "dialog", "id": "duplicateCheckerDialog"},
            ],
        }
    ],
}


def register(app: Flask, services: AppServices) -> None:
    @app.get("/api/duplicate-checker/scan")
    def scan_duplicates():
        root_id = request.args.get("root", "")
        folder = request.args.get("folder", "")
        root_services = _root_services(services, root_id)
        folder_path = resolve_folder(root_services.root, folder)
        groups = find_duplicate_photos(root_id, root_services.root, folder_path)
        return jsonify({
            "root": root_id,
            "folder": folder,
            "groups": groups,
            "duplicateCount": sum(max(0, len(group["photos"]) - 1) for group in groups),
        })

    @app.post("/api/duplicate-checker/delete")
    def delete_duplicates():
        data = request.get_json(silent=True) or {}
        items = data.get("paths", [])
        delete_empty_folders = bool(data.get("deleteEmptyFolders", False))
        if not isinstance(items, list) or not items:
            abort(400, "paths must be a non-empty array.")

        deleted: list[dict[str, str]] = []
        cleanup_folders: list[tuple[Path, Path]] = []
        for item in items:
            if not isinstance(item, str):
                abort(400, "paths must contain only strings.")
            root_id, rel_path = split_rooted_path(item)
            root_services = _root_services(services, root_id)
            path = resolve_media(root_services.root, rel_path)
            if path.suffix.lower() not in PHOTO_EXTENSIONS:
                abort(400, "duplicate checker can delete photos only.")
            parent = path.parent
            result = delete_path(services, root_id, root_services.root, path, "recycle_bin" in services.enabled_plugins)
            cleanup_photo_indexes(root_services, rel_path, path)
            root_services.folder_counts.decrement_deleted_media(path)
            cleanup_folders.append((root_services.root, parent))
            deleted.append({"path": item, **result})

        removed_empty_folders = cleanup_empty_folders(cleanup_folders) if delete_empty_folders else []
        return jsonify({
            "deleted": deleted,
            "mode": "recycle" if "recycle_bin" in services.enabled_plugins else "permanent",
            "removedEmptyFolders": removed_empty_folders,
        })


def find_duplicate_photos(root_id: str, root: Path, folder_path: Path) -> list[dict[str, Any]]:
    by_md5: dict[str, list[dict[str, Any]]] = {}
    for path in iter_photo_files(folder_path):
        digest = md5_file(path)
        rel = to_relative(root, path)
        stat = path.stat()
        by_md5.setdefault(digest, []).append({
            "name": path.name,
            "path": join_rooted_path(root_id, rel),
            "displayPath": str(path.resolve()),
            "rel": rel,
            "size": stat.st_size,
            "mtime": int(stat.st_mtime),
            "thumbUrl": thumb_url(join_rooted_path(root_id, rel)),
        })

    groups: list[dict[str, Any]] = []
    for digest, photos in by_md5.items():
        if len(photos) < 2:
            continue
        photos.sort(key=lambda item: (item["rel"].lower(), item["mtime"]))
        groups.append({
            "md5": digest,
            "size": photos[0]["size"],
            "photos": photos,
        })
    groups.sort(key=lambda group: (-len(group["photos"]), group["photos"][0]["rel"].lower()))
    return groups


def iter_photo_files(folder_path: Path):
    for path in folder_path.rglob("*"):
        try:
            if path.is_file() and path.suffix.lower() in PHOTO_EXTENSIONS:
                yield path
        except OSError:
            continue


def md5_file(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def split_rooted_path(value: str) -> tuple[str, str]:
    parts = value.split("/", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        abort(400, "path must be a rooted media path.")
    return parts[0], parts[1]


def cleanup_empty_folders(folders: list[tuple[Path, Path]]) -> list[str]:
    removed: list[str] = []
    seen: set[Path] = set()
    for root, folder in sorted(folders, key=lambda item: len(item[1].parts), reverse=True):
        current = folder.resolve()
        root = root.resolve()
        while current != root:
            if current in seen:
                current = current.parent
                continue
            seen.add(current)
            try:
                current.relative_to(root)
            except ValueError:
                break
            try:
                current.rmdir()
            except OSError:
                break
            removed.append(str(current))
            current = current.parent
    return removed
