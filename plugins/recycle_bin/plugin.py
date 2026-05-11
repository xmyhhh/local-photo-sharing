from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from flask import Flask, abort, jsonify, request

from core.photo_share.constants import TRASH_DIR
from core.photo_share.context import AppServices
from core.photo_share.paths import join_rooted_path, normalize_rel_path

INDEX_FILE = TRASH_DIR / "index.json"

PLUGIN = {
    "title": "回收站",
    "description": "删除时把文件移动到项目回收站，并允许从独立回收站面板还原原目录。",
    "static_dir": "static",
    "scripts": ["recycle_bin.js"],
    "styles": ["recycle_bin.css"],
    "components": [
        {
            "id": "recycle_bin.open",
            "title": "回收站",
            "description": "查看和还原被删除的文件。",
            "capabilities": [
                {"type": "file_safety", "operations": ["recycle_delete", "restore"]},
            ],
            "triggers": [
                {"type": "topbar_button", "label": "回收站", "action": "recycle_bin.open"},
            ],
            "surfaces": [
                {"type": "dialog", "id": "recycleBinDialog"},
            ],
        }
    ],
}


def register(app: Flask, services: AppServices) -> None:
    @app.get("/api/recycle-bin/status")
    def recycle_bin_status():
        return jsonify({"enabled": "recycle_bin" in services.enabled_plugins})

    @app.get("/api/recycle-bin/items")
    def recycle_bin_items():
        if "recycle_bin" not in services.enabled_plugins:
            abort(404)
        return jsonify({"items": list_items()})

    @app.post("/api/recycle-bin/restore")
    def recycle_bin_restore():
        if "recycle_bin" not in services.enabled_plugins:
            abort(404)
        data = request.get_json(silent=True) or {}
        ids = data.get("ids", [])
        if not isinstance(ids, list) or not ids:
            abort(400, "ids must be a non-empty array.")
        restored: list[dict[str, str]] = []
        records = read_records()
        by_id = {item.get("id"): item for item in records}
        for item_id in ids:
            if not isinstance(item_id, str) or item_id not in by_id:
                continue
            record = by_id[item_id]
            target = restore_record(services, record)
            restored.append({"id": item_id, "path": target})
        restored_ids = {item["id"] for item in restored}
        if restored_ids:
            write_records([item for item in records if item.get("id") not in restored_ids])
        return jsonify({"restored": restored})


def on_enable(services: AppServices) -> None:
    TRASH_DIR.mkdir(parents=True, exist_ok=True)
    services.recycle_bin_recorder = record_deleted_item


def on_disable(services: AppServices) -> None:
    if services.recycle_bin_recorder is record_deleted_item:
        services.recycle_bin_recorder = None


def record_deleted_item(record: dict[str, Any]) -> None:
    records = read_records()
    records.insert(0, record)
    write_records(records)


def list_items() -> list[dict[str, Any]]:
    existing: list[dict[str, Any]] = []
    changed = False
    for record in read_records():
        trash_path = Path(str(record.get("trashPath", "")))
        if not trash_path.exists():
            changed = True
            continue
        existing.append({
            **record,
            "trashName": trash_path.name,
        })
    if changed:
        write_records(existing)
    return existing


def restore_record(services: AppServices, record: dict[str, Any]) -> str:
    root_id = str(record.get("rootId", ""))
    root = services.roots.get(root_id)
    if root is None:
        abort(404, f"root not found: {root_id}")
    original_rel = normalize_rel_path(str(record.get("originalRel", "")))
    if not original_rel:
        abort(400, "originalRel is invalid.")
    source = Path(str(record.get("trashPath", "")))
    if not source.exists():
        abort(404, "trash item no longer exists.")
    target = unique_restore_path(root / original_rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(source, target)
    root_services = services.root_services[root_id]
    root_services.folder_counts.refresh_subtree_async(target.parent)
    return join_rooted_path(root_id, target.relative_to(root).as_posix())


def unique_restore_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(1, 10_000):
        candidate = path.with_name(f"{stem} (restored {index}){suffix}")
        if not candidate.exists():
            return candidate
    abort(409, "Too many duplicate restore names.")


def read_records() -> list[dict[str, Any]]:
    if not INDEX_FILE.exists():
        return []
    try:
        data = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def write_records(records: list[dict[str, Any]]) -> None:
    TRASH_DIR.mkdir(parents=True, exist_ok=True)
    tmp = INDEX_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, INDEX_FILE)
