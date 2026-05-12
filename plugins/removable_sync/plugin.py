from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Any

from flask import Flask, abort, jsonify, request

from core.photo_share.auth import require_admin
from core.photo_share.constants import MEDIA_EXTENSIONS
from core.photo_share.context import AppServices
from core.photo_share.paths import join_rooted_path, resolve_inside, to_relative
from core.photo_share.routes.files import root_id_for_root, split_rooted, unique_child_path
from core.photo_share.routes.gallery import _root_services
from core.photo_share.routes.uploads import sanitize_upload_filename

PLUGIN = {
    "title": "可移动设备同步",
    "description": "从网页所在设备选择 U 盘、SD 卡或文件夹，递归扫描并按内容去重导入到目标文件夹。",
    "static_dir": "static",
    "scripts": ["removable_sync.js"],
    "styles": ["removable_sync.css"],
    "components": [
        {
            "id": "removable_sync.sync_to_folder",
            "title": "从存储设备同步",
            "description": "递归扫描用户选择的来源，把未导入过的照片和视频同步到当前文件夹。",
            "capabilities": [
                {
                    "type": "client_file_sync",
                    "recursive": True,
                    "dedupe": "sha256",
                    "preserveSourceFolders": False,
                }
            ],
            "triggers": [
                {
                    "type": "context_menu",
                    "target": "folder",
                    "label": "从存储设备同步",
                    "icon": "⇄",
                    "action": "removable_sync.sync_to_folder",
                }
            ],
            "surfaces": [
                {"type": "dialog", "id": "removableSyncDialog"},
            ],
        }
    ],
}


def register(app: Flask, services: AppServices) -> None:
    @app.get("/api/removable-sync/index")
    def removable_sync_index():
        require_admin(services)
        root_services, folder_path = resolve_target_folder(services, request.args.get("folder", ""))
        hashes = destination_hashes(folder_path)
        return jsonify({
            "root": root_id_for_root(services, root_services.root),
            "folder": to_relative(root_services.root, folder_path),
            "hashes": sorted(hashes),
            "count": len(hashes),
        })

    @app.post("/api/removable-sync/upload")
    def removable_sync_upload():
        require_admin(services)
        target_value = request.form.get("folder", "")
        client_hash = normalize_hash(request.form.get("sha256", ""))
        root_services, target_folder = resolve_target_folder(services, target_value)
        upload = request.files.get("file")
        if upload is None:
            return jsonify({"message": "No file was uploaded."}), 400
        filename = sanitize_upload_filename(upload.filename or "")
        if not filename:
            return jsonify({"message": "Invalid file name."}), 400
        if Path(filename).suffix.lower() not in MEDIA_EXTENSIONS:
            return jsonify({"name": upload.filename or filename, "status": "rejected", "reason": "Unsupported file type."}), 200

        fd, temp_value = tempfile.mkstemp(
            prefix=".removable-sync-",
            suffix=Path(filename).suffix,
            dir=target_folder,
        )
        os.close(fd)
        temp_path = Path(temp_value)
        try:
            upload.save(temp_path)
            server_hash = sha256_file(temp_path)
            if client_hash and client_hash != server_hash:
                return jsonify({"message": "File hash changed during upload."}), 409
            existing_path = find_hash_in_folder(target_folder, server_hash, exclude=temp_path)
            if existing_path is not None:
                return jsonify({
                    "status": "duplicate",
                    "hash": server_hash,
                    "existing": join_rooted_path(root_id_for_root(services, root_services.root), to_relative(root_services.root, existing_path)),
                })
            destination = unique_child_path(target_folder, filename, want_dir=False)
            os.replace(temp_path, destination)
            root_services.folder_counts.refresh_subtree_async(target_folder)
            return jsonify({
                "status": "saved",
                "hash": server_hash,
                "name": destination.name,
                "path": join_rooted_path(root_id_for_root(services, root_services.root), to_relative(root_services.root, destination)),
                "size": destination.stat().st_size,
            })
        finally:
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except OSError:
                pass


def resolve_target_folder(services: AppServices, value: str):
    if not isinstance(value, str) or not value.strip():
        abort(400, "folder is required.")
    root_id, rel = split_rooted(value)
    root_services = _root_services(services, root_id)
    folder_path = resolve_inside(root_services.root, rel)
    if not folder_path.is_dir():
        abort(404)
    return root_services, folder_path


def destination_hashes(folder_path: Path) -> set[str]:
    hashes: set[str] = set()
    for path in iter_media_files(folder_path):
        hashes.add(sha256_file(path))
    return hashes


def find_hash_in_folder(folder_path: Path, digest: str, exclude: Path | None = None) -> Path | None:
    excluded = exclude.resolve() if exclude is not None else None
    for path in iter_media_files(folder_path):
        if excluded is not None and path.resolve() == excluded:
            continue
        if sha256_file(path) == digest:
            return path
    return None


def iter_media_files(folder_path: Path):
    for path in folder_path.rglob("*"):
        try:
            if path.name.startswith(".removable-sync-"):
                continue
            if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS:
                yield path
        except OSError:
            continue


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_hash(value: Any) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64:
        return ""
    if any(char not in "0123456789abcdef" for char in text):
        return ""
    return text
