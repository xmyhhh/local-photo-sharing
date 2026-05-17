from __future__ import annotations

import json
import math
import time
import uuid
from pathlib import Path
from typing import Any

import PIL.Image as Image
import PIL.ImageChops as ImageChops
import PIL.ImageDraw as ImageDraw
import PIL.ImageFilter as ImageFilter
import PIL.ImageOps as ImageOps
from flask import Flask, abort, jsonify, request, send_file

from core.photo_share.auth import require_admin, require_path_access
from core.photo_share.constants import CACHE_DIR, PHOTO_EXTENSIONS
from core.photo_share.context import AppServices
from core.photo_share.image_decode import load_photo_image
from core.photo_share.paths import image_url, join_rooted_path, parse_rooted_path, resolve_folder, resolve_photo, send_cached_file, thumb_url, to_relative
from core.photo_share.routes.gallery import _root_services

PLUGIN_NAME = "collage"
COLLAGE_CACHE_VERSION = 1
COLLAGE_CACHE_DIR = CACHE_DIR / "collage"
COLLAGE_STORE_FILE = COLLAGE_CACHE_DIR / "groups.json"
OUTPUT_DIR = COLLAGE_CACHE_DIR / "outputs"
MAX_GROUP_ITEMS = 80
MAX_POOL_ITEMS = 500
MAX_RENDER_SIDE = 4096
DEFAULT_SETTINGS = {
    "layout": "grid",
    "templateId": "",
    "stripDirection": "vertical",
    "width": 2400,
    "height": 1600,
    "gap": 24,
    "overlap": 0,
    "blendSpeed": 1,
    "padding": 48,
    "background": "#f7f3ea",
    "fit": "cover",
    "radius": 18,
    "shadow": True,
    "columns": 3,
    "rows": 2,
    "aspect": "auto",
}

COLLAGE_TEMPLATES: dict[int, list[dict[str, Any]]] = {
    1: [{"id": "1-0", "name": "单图", "boxes": [(0, 0, 100, 100)]}],
    2: [
        {"id": "2-0", "name": "左右", "boxes": [(0, 0, 50, 100), (50, 0, 50, 100)]},
        {"id": "2-1", "name": "上下", "boxes": [(0, 0, 100, 50), (0, 50, 100, 50)]},
        {"id": "2-2", "name": "主次", "boxes": [(0, 0, 66.6667, 100), (66.6667, 0, 33.3333, 100)]},
        {"id": "2-3", "name": "封面", "boxes": [(0, 0, 100, 66.6667), (0, 66.6667, 100, 33.3333)]},
    ],
    3: [
        {"id": "3-0", "name": "左主图", "boxes": [(0, 0, 66.6667, 100), (66.6667, 0, 33.3333, 50), (66.6667, 50, 33.3333, 50)]},
        {"id": "3-1", "name": "上主图", "boxes": [(0, 0, 100, 66.6667), (0, 66.6667, 50, 33.3333), (50, 66.6667, 50, 33.3333)]},
        {"id": "3-2", "name": "三列", "boxes": [(0, 0, 33.3333, 100), (33.3333, 0, 33.3334, 100), (66.6667, 0, 33.3333, 100)]},
        {"id": "3-3", "name": "错落", "boxes": [(0, 0, 50, 50), (50, 0, 50, 100), (0, 50, 50, 50)]},
    ],
    4: [
        {"id": "4-0", "name": "四宫格", "boxes": [(0, 0, 50, 50), (50, 0, 50, 50), (0, 50, 50, 50), (50, 50, 50, 50)]},
        {"id": "4-1", "name": "左主图", "boxes": [(0, 0, 66.6667, 100), (66.6667, 0, 33.3333, 33.3333), (66.6667, 33.3333, 33.3333, 33.3334), (66.6667, 66.6667, 33.3333, 33.3333)]},
        {"id": "4-2", "name": "上宽幅", "boxes": [(0, 0, 100, 50), (0, 50, 33.3333, 50), (33.3333, 50, 33.3334, 50), (66.6667, 50, 33.3333, 50)]},
        {"id": "4-3", "name": "杂志", "boxes": [(0, 0, 50, 66.6667), (50, 0, 50, 33.3333), (50, 33.3333, 50, 33.3334), (0, 66.6667, 100, 33.3333)]},
    ],
    5: [
        {"id": "5-0", "name": "右主图", "boxes": [(0, 0, 33.3333, 33.3333), (33.3333, 0, 66.6667, 66.6667), (0, 33.3333, 33.3333, 33.3334), (0, 66.6667, 33.3333, 33.3333), (33.3333, 66.6667, 66.6667, 33.3333)]},
        {"id": "5-1", "name": "中主图", "boxes": [(0, 0, 50, 25), (50, 0, 50, 25), (0, 25, 100, 50), (0, 75, 50, 25), (50, 75, 50, 25)]},
        {"id": "5-2", "name": "竖版拼贴", "boxes": [(0, 0, 40, 50), (40, 0, 60, 25), (40, 25, 60, 25), (0, 50, 60, 50), (60, 50, 40, 50)]},
    ],
    6: [
        {"id": "6-0", "name": "上主图", "boxes": [(0, 0, 100, 50), (0, 50, 33.3333, 25), (33.3333, 50, 33.3334, 25), (66.6667, 50, 33.3333, 50), (0, 75, 33.3333, 25), (33.3333, 75, 33.3334, 25)]},
        {"id": "6-1", "name": "双主图", "boxes": [(0, 0, 50, 50), (50, 0, 50, 50), (0, 50, 25, 50), (25, 50, 25, 50), (50, 50, 25, 50), (75, 50, 25, 50)]},
        {"id": "6-2", "name": "六宫格", "boxes": [(0, 0, 33.3333, 50), (33.3333, 0, 33.3334, 50), (66.6667, 0, 33.3333, 50), (0, 50, 33.3333, 50), (33.3333, 50, 33.3334, 50), (66.6667, 50, 33.3333, 50)]},
    ],
    7: [
        {"id": "7-0", "name": "中心", "boxes": [(0, 0, 25, 25), (25, 0, 50, 50), (75, 0, 25, 25), (0, 25, 25, 50), (75, 25, 25, 50), (0, 75, 50, 25), (50, 75, 50, 25)]},
        {"id": "7-1", "name": "横向故事", "boxes": [(0, 0, 50, 50), (50, 0, 25, 25), (75, 0, 25, 25), (50, 25, 50, 25), (0, 50, 25, 50), (25, 50, 25, 50), (50, 50, 50, 50)]},
    ],
    8: [
        {"id": "8-0", "name": "八格交错", "boxes": [(0, 0, 25, 25), (25, 0, 75, 25), (0, 25, 75, 25), (75, 25, 25, 25), (0, 50, 25, 25), (25, 50, 75, 25), (0, 75, 75, 25), (75, 75, 25, 25)]},
        {"id": "8-1", "name": "大图收束", "boxes": [(0, 0, 50, 50), (50, 0, 25, 25), (75, 0, 25, 25), (50, 25, 50, 25), (0, 50, 25, 25), (25, 50, 25, 25), (50, 50, 50, 50), (0, 75, 50, 25)]},
    ],
    9: [
        {"id": "9-0", "name": "九宫格", "boxes": [(0, 0, 33.3333, 33.3333), (33.3333, 0, 33.3334, 33.3333), (66.6667, 0, 33.3333, 33.3333), (0, 33.3333, 33.3333, 33.3334), (33.3333, 33.3333, 33.3334, 33.3334), (66.6667, 33.3333, 33.3333, 33.3334), (0, 66.6667, 33.3333, 33.3333), (33.3333, 66.6667, 33.3334, 33.3333), (66.6667, 66.6667, 33.3333, 33.3333)]},
        {"id": "9-1", "name": "中心主图", "boxes": [(0, 0, 50, 25), (50, 0, 50, 25), (0, 25, 25, 50), (25, 25, 50, 50), (75, 25, 25, 50), (0, 75, 25, 25), (25, 75, 25, 25), (50, 75, 25, 25), (75, 75, 25, 25)]},
        {"id": "9-2", "name": "大小拼贴", "boxes": [(0, 0, 33.3333, 33.3333), (33.3333, 0, 16.6667, 16.6667), (50, 0, 50, 50), (33.3333, 16.6667, 16.6667, 16.6666), (0, 33.3333, 16.6667, 16.6667), (16.6667, 33.3333, 16.6666, 16.6667), (33.3333, 33.3333, 16.6667, 16.6667), (0, 50, 50, 50), (50, 50, 50, 50)]},
    ],
    10: [
        {"id": "10-0", "name": "十图网格", "boxes": [(0, 0, 20, 50), (20, 0, 20, 25), (40, 0, 40, 50), (80, 0, 20, 25), (20, 25, 20, 25), (80, 25, 20, 25), (0, 50, 25, 50), (25, 50, 25, 50), (50, 50, 25, 50), (75, 50, 25, 50)]},
    ],
}


PLUGIN = {
    "title": "拼图工作台",
    "description": "把选中的照片加入拼图工作组，支持多种自动排版和自由编辑，并在服务端缓存成品图。",
    "static_dir": "static",
    "scripts": ["collage.js"],
    "styles": ["collage.css"],
    "components": [
        {
            "id": "collage.workbench",
            "title": "拼图工作台",
            "description": "管理拼图工作组，选择网格、海报、胶片、瀑布流等排版，或在自由模式中拖拽编辑版面。",
            "capabilities": [
                {
                    "type": "file_handler",
                    "extensions": sorted(PHOTO_EXTENSIONS),
                    "multi": True,
                    "operations": ["add_to_collage", "open_workbench", "render", "download"],
                },
                {"type": "project", "operations": ["create_group", "update_group", "delete_group"]},
            ],
            "triggers": [
                {"type": "topbar_button", "label": "拼图", "icon": "▦", "action": "collage.open"},
                {"type": "context_menu", "target": "file", "label": "添加到拼图", "icon": "▦", "action": "collage.add_file"},
                {
                    "type": "context_menu",
                    "target": "file_selection",
                    "label": "添加到拼图",
                    "icon": "▦",
                    "action": "collage.add_selection",
                },
            ],
            "surfaces": [
                {"type": "dedicated_page", "route": "/collage"},
                {"type": "main_tab", "label": "拼图", "route": "/collage"},
            ],
        }
    ],
}


def register(app: Flask, services: AppServices) -> None:
    @app.get("/collage")
    def collage_page():
        require_admin(services)
        page = Path(__file__).resolve().parent / "static" / "collage.html"
        return send_file(page, mimetype="text/html", conditional=True)

    @app.get("/api/collage/groups")
    def list_groups():
        require_admin(services)
        store = load_store()
        return jsonify({"groups": [serialize_group(group) for group in store["groups"]]})

    @app.get("/api/collage/pool")
    def collage_pool():
        require_admin(services)
        store = load_store()
        return jsonify({"items": serialize_pool(store.get("pool", []))})

    @app.post("/api/collage/pool")
    def add_collage_pool():
        require_admin(services)
        data = request.get_json(silent=True) or {}
        paths = normalize_photo_paths(services, data.get("paths", []), limit=MAX_POOL_ITEMS)
        store = load_store()
        store["pool"] = merge_pool_items(store.get("pool", []), build_pool_items(services, paths))
        save_store(store)
        return jsonify({"items": serialize_pool(store["pool"])})

    @app.delete("/api/collage/pool")
    def remove_collage_pool_items():
        require_admin(services)
        data = request.get_json(silent=True) or {}
        paths = normalize_photo_paths(services, data.get("paths", []), limit=MAX_POOL_ITEMS)
        remove = set(paths)
        store = load_store()
        store["pool"] = [item for item in store.get("pool", []) if str(item.get("path") or "") not in remove]
        save_store(store)
        return jsonify({"items": serialize_pool(store["pool"])})

    @app.get("/api/collage/library")
    def collage_library():
        require_admin(services)
        root_id = request.args.get("root", "")
        folder = request.args.get("folder", "")
        if not root_id:
            return jsonify({
                "root": "",
                "folder": "",
                "parent": "",
                "entries": [
                    {
                        "type": "folder",
                        "name": root.name or item_root_id,
                        "path": item_root_id,
                        "root": item_root_id,
                    }
                    for item_root_id, root in services.roots.items()
                ],
            })
        root_services = _root_services(services, root_id)
        folder_path = resolve_folder(root_services.root, folder)
        entries = []
        for child in sorted(folder_path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
            try:
                if child.is_dir():
                    rel = to_relative(root_services.root, child)
                    entries.append({
                        "type": "folder",
                        "name": child.name,
                        "path": join_rooted_path(root_id, rel),
                        "root": root_id,
                        "folder": rel,
                    })
                elif child.is_file() and child.suffix.lower() in PHOTO_EXTENSIONS:
                    rel = to_relative(root_services.root, child)
                    rooted = join_rooted_path(root_id, rel)
                    stat = child.stat()
                    entries.append({
                        "type": "photo",
                        "name": child.name,
                        "path": rooted,
                        "root": root_id,
                        "folder": parent_rel(rel),
                        "mtime": int(stat.st_mtime),
                        "thumbUrl": thumb_url(rooted, "small"),
                    })
            except OSError:
                continue
        return jsonify({
            "root": root_id,
            "folder": folder,
            "parent": parent_rel(folder),
            "entries": entries,
        })

    @app.post("/api/collage/groups")
    def create_group():
        require_admin(services)
        data = request.get_json(silent=True) or {}
        paths = normalize_photo_paths(services, data.get("paths", []))
        name = str(data.get("name") or "").strip() or next_group_name(load_store()["groups"])
        group = {
            "id": uuid.uuid4().hex[:16],
            "name": name[:80],
            "items": build_items(services, paths),
            "settings": normalize_settings(data.get("settings")),
            "createdAt": int(time.time()),
            "updatedAt": int(time.time()),
            "output": None,
        }
        store = load_store()
        store["groups"].insert(0, group)
        render_group(services, group)
        save_store(store)
        return jsonify({"group": serialize_group(group)}), 201

    @app.get("/api/collage/groups/<group_id>")
    def get_group(group_id: str):
        require_admin(services)
        group = find_group_or_404(load_store(), group_id)
        return jsonify({"group": serialize_group(group)})

    @app.patch("/api/collage/groups/<group_id>")
    def update_group(group_id: str):
        require_admin(services)
        data = request.get_json(silent=True) or {}
        store = load_store()
        group = find_group_or_404(store, group_id)
        if "name" in data:
            name = str(data.get("name") or "").strip()
            if name:
                group["name"] = name[:80]
        if "settings" in data:
            group["settings"] = normalize_settings(data.get("settings"), group.get("settings"))
        if "items" in data:
            items = data.get("items")
            if not isinstance(items, list):
                abort(400, "items must be an array.")
            group["items"] = normalize_items_from_payload(services, items)
        if "paths" in data:
            paths = normalize_photo_paths(services, data.get("paths", []))
            group["items"] = merge_items(group.get("items", []), build_items(services, paths))
        group["updatedAt"] = int(time.time())
        render_group(services, group)
        save_store(store)
        return jsonify({"group": serialize_group(group)})

    @app.post("/api/collage/groups/<group_id>/render")
    def rerender_group(group_id: str):
        require_admin(services)
        store = load_store()
        group = find_group_or_404(store, group_id)
        render_group(services, group)
        group["updatedAt"] = int(time.time())
        save_store(store)
        return jsonify({"group": serialize_group(group)})

    @app.delete("/api/collage/groups/<group_id>")
    def delete_group(group_id: str):
        require_admin(services)
        store = load_store()
        groups = store["groups"]
        group = next((item for item in groups if item.get("id") == group_id), None)
        if group is None:
            abort(404)
        groups.remove(group)
        delete_group_output(group)
        save_store(store)
        return jsonify({"deleted": group_id})

    @app.post("/api/collage/groups/<group_id>/items")
    def add_group_items(group_id: str):
        require_admin(services)
        data = request.get_json(silent=True) or {}
        paths = normalize_photo_paths(services, data.get("paths", []))
        store = load_store()
        group = find_group_or_404(store, group_id)
        group["items"] = merge_items(group.get("items", []), build_items(services, paths))
        group["updatedAt"] = int(time.time())
        render_group(services, group)
        save_store(store)
        return jsonify({"group": serialize_group(group)})

    @app.get("/api/collage/groups/<group_id>/image")
    def preview_group(group_id: str):
        require_admin(services)
        group = find_group_or_404(load_store(), group_id)
        output = output_path_for_group(group)
        if not output.is_file():
            abort(404)
        return send_cached_file(output, mimetype="image/jpeg")

    @app.get("/api/collage/groups/<group_id>/download")
    def download_group(group_id: str):
        require_admin(services)
        group = find_group_or_404(load_store(), group_id)
        output = output_path_for_group(group)
        if not output.is_file():
            abort(404)
        return send_cached_file(
            output,
            mimetype="image/jpeg",
            as_attachment=True,
            download_name=f"{safe_filename(group.get('name') or 'collage')}.jpg",
        )


def load_store() -> dict[str, Any]:
    COLLAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(COLLAGE_STORE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": COLLAGE_CACHE_VERSION, "groups": [], "pool": []}
    groups = data.get("groups") if isinstance(data, dict) else []
    if not isinstance(groups, list):
        groups = []
    pool = data.get("pool") if isinstance(data, dict) else []
    if not isinstance(pool, list):
        pool = []
    return {
        "version": COLLAGE_CACHE_VERSION,
        "groups": [group for group in groups if isinstance(group, dict)],
        "pool": [item for item in pool if isinstance(item, dict)],
    }


def save_store(store: dict[str, Any]) -> None:
    COLLAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"version": COLLAGE_CACHE_VERSION, "groups": store.get("groups", []), "pool": store.get("pool", [])}
    tmp_path = COLLAGE_STORE_FILE.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp_path.replace(COLLAGE_STORE_FILE)


def find_group_or_404(store: dict[str, Any], group_id: str) -> dict[str, Any]:
    group = next((item for item in store["groups"] if item.get("id") == group_id), None)
    if group is None:
        abort(404)
    return group


def normalize_photo_paths(services: AppServices, value: Any, limit: int = MAX_GROUP_ITEMS) -> list[str]:
    if not isinstance(value, list):
        abort(400, "paths must be an array.")
    paths: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        require_path_access(services, item)
        root_id, rel = parse_rooted_path(item)
        root_services = _root_services(services, root_id)
        path = resolve_photo(root_services.root, rel)
        if path.suffix.lower() not in PHOTO_EXTENSIONS:
            continue
        normalized = f"{root_id}/{rel}"
        if normalized not in seen:
            seen.add(normalized)
            paths.append(normalized)
    return paths[:limit]


def build_pool_items(services: AppServices, paths: list[str]) -> list[dict[str, Any]]:
    items = []
    for item in build_items(services, paths):
        items.append({
            "path": item["path"],
            "name": item["name"],
            "mtime": item["mtime"],
            "width": item["width"],
            "height": item["height"],
            "addedAt": int(time.time()),
        })
    return items


def merge_pool_items(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = [item for item in existing if isinstance(item, dict) and item.get("path")]
    seen = {str(item.get("path")) for item in result}
    for item in incoming:
        path = str(item.get("path") or "")
        if not path:
            continue
        if path in seen:
            result = [current for current in result if str(current.get("path")) != path]
        seen.add(path)
        result.insert(0, item)
    return result[:MAX_POOL_ITEMS]


def build_items(services: AppServices, paths: list[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for photo_path in paths:
        root_id, rel = parse_rooted_path(photo_path)
        root_services = _root_services(services, root_id)
        path = resolve_photo(root_services.root, rel)
        width, height = image_size(path)
        stat = path.stat()
        items.append({
            "id": uuid.uuid4().hex[:12],
            "path": photo_path,
            "name": path.name,
            "mtime": int(stat.st_mtime),
            "width": width,
            "height": height,
            "x": 0,
            "y": 0,
            "w": 0,
            "h": 0,
            "cropX": 50,
            "cropY": 50,
        })
    return items


def normalize_items_from_payload(services: AppServices, items: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in items[:MAX_GROUP_ITEMS]:
        if not isinstance(item, dict):
            continue
        photo_path = str(item.get("path") or "")
        paths = normalize_photo_paths(services, [photo_path])
        if not paths:
            continue
        built = build_items(services, paths)[0]
        built["id"] = str(item.get("id") or built["id"])[:32]
        for key in ("x", "y", "w", "h"):
            built[key] = clamp_number(item.get(key), 0, 10_000, 0)
        built["cropX"] = clamp_number(item.get("cropX"), 0, 100, 50)
        built["cropY"] = clamp_number(item.get("cropY"), 0, 100, 50)
        normalized.append(built)
    return normalized


def merge_items(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_path = {str(item.get("path")): item for item in existing if isinstance(item, dict)}
    merged = [item for item in existing if isinstance(item, dict)]
    for item in incoming:
        if item["path"] in by_path:
            continue
        merged.append(item)
    return merged[:MAX_GROUP_ITEMS]


def normalize_settings(value: Any, previous: Any = None) -> dict[str, Any]:
    settings = {**DEFAULT_SETTINGS}
    if isinstance(previous, dict):
        settings.update(previous)
    if isinstance(value, dict):
        settings.update(value)
    settings["layout"] = settings["layout"] if settings["layout"] in {"grid", "masonry", "hero", "film", "free", "template", "strip"} else "grid"
    settings["templateId"] = str(settings.get("templateId") or "")[:32]
    settings["stripDirection"] = settings["stripDirection"] if settings.get("stripDirection") in {"vertical", "horizontal"} else "vertical"
    settings["width"] = int(clamp_number(settings.get("width"), 800, MAX_RENDER_SIDE, DEFAULT_SETTINGS["width"]))
    settings["height"] = int(clamp_number(settings.get("height"), 800, MAX_RENDER_SIDE, DEFAULT_SETTINGS["height"]))
    settings["gap"] = int(clamp_number(settings.get("gap"), 0, 120, DEFAULT_SETTINGS["gap"]))
    settings["overlap"] = int(clamp_number(settings.get("overlap"), 0, 720, DEFAULT_SETTINGS["overlap"]))
    settings["blendSpeed"] = clamp_number(settings.get("blendSpeed"), 0.25, 4, DEFAULT_SETTINGS["blendSpeed"])
    settings["padding"] = int(clamp_number(settings.get("padding"), 0, 240, DEFAULT_SETTINGS["padding"]))
    settings["radius"] = int(clamp_number(settings.get("radius"), 0, 80, DEFAULT_SETTINGS["radius"]))
    settings["columns"] = int(clamp_number(settings.get("columns"), 1, 12, DEFAULT_SETTINGS["columns"]))
    settings["rows"] = int(clamp_number(settings.get("rows"), 1, 12, DEFAULT_SETTINGS["rows"]))
    settings["fit"] = settings["fit"] if settings["fit"] in {"cover", "contain"} else "cover"
    settings["shadow"] = bool(settings.get("shadow", True))
    settings["background"] = normalize_color(settings.get("background"), DEFAULT_SETTINGS["background"])
    return settings


def clamp_number(value: Any, minimum: float, maximum: float, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(parsed):
        return fallback
    return max(minimum, min(maximum, parsed))


def normalize_color(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    if len(text) == 7 and text.startswith("#") and all(char in "0123456789abcdefABCDEF" for char in text[1:]):
        return text
    return fallback


def render_group(services: AppServices, group: dict[str, Any]) -> None:
    settings = normalize_settings(group.get("settings"))
    group["settings"] = settings
    items = [item for item in group.get("items", []) if isinstance(item, dict)]
    render_settings = effective_render_settings(settings, items)
    output = output_path_for_group(group)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas = Image.new("RGB", (render_settings["width"], render_settings["height"]), render_settings["background"])
    if not items:
        canvas.save(output, "JPEG", quality=92, optimize=True)
        group["output"] = output.name
        return

    boxes = layout_boxes(render_settings, items)
    for index, (item, box) in enumerate(zip(items, boxes)):
        try:
            root_id, rel = parse_rooted_path(str(item.get("path") or ""))
            root_services = _root_services(services, root_id)
            source = resolve_photo(root_services.root, rel)
            with load_photo_image(source) as image:
                draw_image(canvas, image, box, render_settings, item, index)
        except Exception:
            draw_missing(canvas, box)
    canvas.save(output, "JPEG", quality=94, optimize=True)
    group["output"] = output.name


def effective_render_settings(settings: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    render_settings = dict(settings)
    if settings["layout"] != "strip" or not items:
        return render_settings
    pad = settings["padding"]
    gap = settings["gap"]
    overlap = settings["overlap"]
    if settings["stripDirection"] == "horizontal":
        inner_h = max(1, settings["height"] - pad * 2)
        total_width = sum(inner_h * (clamp_number(item.get("width"), 1, 10_000, 4) / clamp_number(item.get("height"), 1, 10_000, 3)) for item in items)
        render_settings["width"] = int(clamp_number(round(pad * 2 + total_width + gap * max(0, len(items) - 1) - overlap * max(0, len(items) - 1)), 800, MAX_RENDER_SIDE, settings["width"]))
        return render_settings
    inner_w = max(1, settings["width"] - pad * 2)
    total_height = sum(inner_w * (clamp_number(item.get("height"), 1, 10_000, 3) / clamp_number(item.get("width"), 1, 10_000, 4)) for item in items)
    render_settings["height"] = int(clamp_number(round(pad * 2 + total_height + gap * max(0, len(items) - 1) - overlap * max(0, len(items) - 1)), 800, MAX_RENDER_SIDE, settings["height"]))
    return render_settings


def layout_boxes(settings: dict[str, Any], items: list[dict[str, Any]]) -> list[tuple[int, int, int, int]]:
    if settings["layout"] == "free":
        boxes = []
        for item in items:
            box = (
                int(clamp_number(item.get("x"), 0, settings["width"], settings["padding"])),
                int(clamp_number(item.get("y"), 0, settings["height"], settings["padding"])),
                int(clamp_number(item.get("w"), 1, settings["width"], 320)),
                int(clamp_number(item.get("h"), 1, settings["height"], 240)),
            )
            boxes.append(box)
        return boxes
    if settings["layout"] == "hero":
        return hero_boxes(settings, len(items))
    if settings["layout"] == "film":
        return film_boxes(settings, len(items))
    if settings["layout"] == "masonry":
        return masonry_boxes(settings, items)
    if settings["layout"] == "template":
        return template_boxes(settings, len(items))
    if settings["layout"] == "strip":
        return strip_boxes(settings, items)
    return grid_boxes(settings, len(items))


def templates_for_count(count: int) -> list[dict[str, Any]]:
    if count <= 0:
        return []
    if count in COLLAGE_TEMPLATES:
        return COLLAGE_TEMPLATES[count]
    return generated_templates(count)


def generated_templates(count: int) -> list[dict[str, Any]]:
    columns = math.ceil(math.sqrt(count))
    rows = math.ceil(count / columns)
    cell_w = 100 / columns
    cell_h = 100 / rows
    boxes = [((index % columns) * cell_w, (index // columns) * cell_h, cell_w, cell_h) for index in range(count)]
    templates = [{"id": f"{count}-grid", "name": f"{count} 宫格", "boxes": boxes}]
    if count >= 5:
        hero_boxes_data = [(0, 0, 50, 50)]
        small_columns = 2
        small_rows = math.ceil((count - 1) / small_columns)
        small_w = 50 / small_columns
        small_h = 100 / small_rows
        for index in range(1, count):
            local = index - 1
            hero_boxes_data.append((50 + (local % small_columns) * small_w, (local // small_columns) * small_h, small_w, small_h))
        templates.append({"id": f"{count}-hero", "name": "主图拼贴", "boxes": hero_boxes_data})
    return templates


def selected_template(settings: dict[str, Any], count: int) -> dict[str, Any] | None:
    templates = templates_for_count(count)
    if not templates:
        return None
    template_id = str(settings.get("templateId") or "")
    return next((template for template in templates if template["id"] == template_id), templates[0])


def template_boxes(settings: dict[str, Any], count: int) -> list[tuple[int, int, int, int]]:
    template = selected_template(settings, count)
    if template is None:
        return grid_boxes(settings, count)
    pad = settings["padding"]
    gap = settings["gap"]
    inner_w = settings["width"] - pad * 2
    inner_h = settings["height"] - pad * 2
    boxes = []
    for left, top, width, height in template["boxes"][:count]:
        x_inset = 0 if left <= 0 else gap / 2
        y_inset = 0 if top <= 0 else gap / 2
        right_inset = 0 if left + width >= 99.999 else gap / 2
        bottom_inset = 0 if top + height >= 99.999 else gap / 2
        x = pad + inner_w * (left / 100) + x_inset
        y = pad + inner_h * (top / 100) + y_inset
        w = inner_w * (width / 100) - x_inset - right_inset
        h = inner_h * (height / 100) - y_inset - bottom_inset
        boxes.append((round(x), round(y), max(1, round(w)), max(1, round(h))))
    return boxes


def grid_boxes(settings: dict[str, Any], count: int) -> list[tuple[int, int, int, int]]:
    columns = min(settings["columns"], max(1, count))
    rows = max(settings["rows"], math.ceil(count / columns))
    pad = settings["padding"]
    gap = settings["gap"]
    cell_w = (settings["width"] - pad * 2 - gap * (columns - 1)) / columns
    cell_h = (settings["height"] - pad * 2 - gap * (rows - 1)) / rows
    return [
        (round(pad + (index % columns) * (cell_w + gap)), round(pad + (index // columns) * (cell_h + gap)), round(cell_w), round(cell_h))
        for index in range(count)
    ]


def strip_boxes(settings: dict[str, Any], items: list[dict[str, Any]]) -> list[tuple[int, int, int, int]]:
    count = len(items)
    if count <= 0:
        return []
    pad = settings["padding"]
    gap = settings["gap"]
    horizontal = settings["stripDirection"] == "horizontal"
    overlap = min(settings["overlap"], max(0, int((settings["width"] if horizontal else settings["height"]) * 0.4)))
    if horizontal:
        frame_h = max(1, settings["height"] - pad * 2)
        boxes = []
        x = float(pad)
        for item in items:
            frame_w = frame_h * (clamp_number(item.get("width"), 1, 10_000, 4) / clamp_number(item.get("height"), 1, 10_000, 3))
            boxes.append((round(x), pad, round(frame_w), frame_h))
            x += frame_w + gap - overlap
        return boxes
    frame_w = max(1, settings["width"] - pad * 2)
    boxes = []
    y = float(pad)
    for item in items:
        frame_h = frame_w * (clamp_number(item.get("height"), 1, 10_000, 3) / clamp_number(item.get("width"), 1, 10_000, 4))
        boxes.append((pad, round(y), frame_w, round(frame_h)))
        y += frame_h + gap - overlap
    return boxes


def hero_boxes(settings: dict[str, Any], count: int) -> list[tuple[int, int, int, int]]:
    if count <= 1:
        return [(settings["padding"], settings["padding"], settings["width"] - settings["padding"] * 2, settings["height"] - settings["padding"] * 2)]
    pad = settings["padding"]
    gap = settings["gap"]
    side_w = max(280, int((settings["width"] - pad * 2 - gap) * 0.32))
    hero_w = settings["width"] - pad * 2 - gap - side_w
    boxes = [(pad, pad, hero_w, settings["height"] - pad * 2)]
    side_count = count - 1
    side_h = (settings["height"] - pad * 2 - gap * (side_count - 1)) / side_count
    for index in range(side_count):
        boxes.append((pad + hero_w + gap, round(pad + index * (side_h + gap)), side_w, round(side_h)))
    return boxes


def film_boxes(settings: dict[str, Any], count: int) -> list[tuple[int, int, int, int]]:
    pad = settings["padding"]
    gap = settings["gap"]
    boxes = []
    cell_w = (settings["width"] - pad * 2 - gap * (count - 1)) / max(1, count)
    height = settings["height"] - pad * 2
    for index in range(count):
        stagger = int((height * 0.08) * (1 if index % 2 else -1))
        y = pad + max(0, stagger)
        h = height - abs(stagger)
        boxes.append((round(pad + index * (cell_w + gap)), y, round(cell_w), h))
    return boxes


def masonry_boxes(settings: dict[str, Any], items: list[dict[str, Any]]) -> list[tuple[int, int, int, int]]:
    columns = min(settings["columns"], max(1, len(items)))
    pad = settings["padding"]
    gap = settings["gap"]
    col_w = (settings["width"] - pad * 2 - gap * (columns - 1)) / columns
    col_y = [float(pad)] * columns
    boxes = []
    for item in items:
        ratio = clamp_number(item.get("height"), 1, 10_000, 3) / clamp_number(item.get("width"), 1, 10_000, 4)
        height = max(180, min(settings["height"] * 0.62, col_w * ratio))
        col = min(range(columns), key=lambda idx: col_y[idx])
        boxes.append((round(pad + col * (col_w + gap)), round(col_y[col]), round(col_w), round(height)))
        col_y[col] += height + gap
    scale = min(1.0, (settings["height"] - pad) / max(col_y)) if max(col_y) > settings["height"] - pad else 1.0
    if scale >= 1:
        return boxes
    return [(x, round(pad + (y - pad) * scale), w, max(1, round(h * scale))) for x, y, w, h in boxes]


def draw_image(canvas: Image.Image, image: Image.Image, box: tuple[int, int, int, int], settings: dict[str, Any], item: dict[str, Any] | None = None, index: int = 0) -> None:
    x, y, w, h = box
    if w <= 0 or h <= 0:
        return
    frame = cover_image(image.convert("RGB"), w, h, item or {}) if settings["fit"] == "cover" else contain_image(image.convert("RGB"), w, h, settings["background"])
    radius = min(settings["radius"], w // 2, h // 2)
    if settings["shadow"]:
        shadow = Image.new("RGBA", (w + 20, h + 20), (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow)
        shadow_draw.rounded_rectangle((10, 10, w + 10, h + 10), radius=radius, fill=(0, 0, 0, 46))
        shadow = shadow.filter(ImageFilter.GaussianBlur(8))
        canvas.paste(shadow.convert("RGB"), (x - 10, y - 8), shadow.split()[-1])
    blend = blend_axis(settings, index)
    if radius or blend:
        mask = image_paste_mask(w, h, radius, blend, settings)
        canvas.paste(frame, (x, y), mask)
    else:
        canvas.paste(frame, (x, y))


def blend_axis(settings: dict[str, Any], index: int) -> str:
    if settings["layout"] != "strip" or index <= 0 or settings["overlap"] <= 0:
        return ""
    return "x" if settings["stripDirection"] == "horizontal" else "y"


def image_paste_mask(width: int, height: int, radius: int, blend: str, settings: dict[str, Any]) -> Image.Image:
    mask = Image.new("L", (width, height), 255)
    if blend:
        overlap = min(settings["overlap"], width if blend == "x" else height)
        speed = settings["blendSpeed"]
        if overlap > 0:
            if blend == "x":
                for x in range(overlap):
                    alpha = round(255 * ((x + 1) / overlap) ** speed)
                    ImageDraw.Draw(mask).line((x, 0, x, height), fill=alpha)
            else:
                draw = ImageDraw.Draw(mask)
                for y in range(overlap):
                    alpha = round(255 * ((y + 1) / overlap) ** speed)
                    draw.line((0, y, width, y), fill=alpha)
    if radius:
        radius_mask = Image.new("L", (width, height), 0)
        ImageDraw.Draw(radius_mask).rounded_rectangle((0, 0, width, height), radius=radius, fill=255)
        mask = ImageChops.multiply(mask, radius_mask)
    return mask


def contain_image(image: Image.Image, width: int, height: int, background: str) -> Image.Image:
    image.thumbnail((width, height), Image.Resampling.LANCZOS)
    frame = Image.new("RGB", (width, height), background)
    frame.paste(image, ((width - image.width) // 2, (height - image.height) // 2))
    return frame


def cover_image(image: Image.Image, width: int, height: int, item: dict[str, Any]) -> Image.Image:
    scale = max(width / image.width, height / image.height)
    resized_width = max(1, round(image.width * scale))
    resized_height = max(1, round(image.height * scale))
    resized = image.resize((resized_width, resized_height), Image.Resampling.LANCZOS)
    overflow_x = max(0, resized_width - width)
    overflow_y = max(0, resized_height - height)
    crop_x = clamp_number(item.get("cropX"), 0, 100, 50) / 100
    crop_y = clamp_number(item.get("cropY"), 0, 100, 50) / 100
    left = round(overflow_x * crop_x)
    top = round(overflow_y * crop_y)
    return resized.crop((left, top, left + width, top + height))


def draw_missing(canvas: Image.Image, box: tuple[int, int, int, int]) -> None:
    x, y, w, h = box
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((x, y, x + w, y + h), fill="#ddd7cc")
    draw.line((x, y, x + w, y + h), fill="#b8afa1", width=4)
    draw.line((x + w, y, x, y + h), fill="#b8afa1", width=4)


def image_size(path: Path) -> tuple[int, int]:
    try:
        with load_photo_image(path) as image:
            return image.size
    except Exception:
        return 0, 0


def output_path_for_group(group: dict[str, Any]) -> Path:
    group_id = str(group.get("id") or "")
    filename = str(group.get("output") or f"{group_id}.jpg")
    if not filename.endswith(".jpg"):
        filename = f"{group_id}.jpg"
    return OUTPUT_DIR / filename


def delete_group_output(group: dict[str, Any]) -> None:
    output = output_path_for_group(group)
    try:
        output.unlink(missing_ok=True)
    except OSError:
        pass


def serialize_group(group: dict[str, Any]) -> dict[str, Any]:
    group_id = str(group.get("id") or "")
    items = [serialize_item(item) for item in group.get("items", []) if isinstance(item, dict)]
    output = output_path_for_group(group)
    image_mtime = int(output.stat().st_mtime) if output.is_file() else 0
    return {
        "id": group_id,
        "name": group.get("name") or "未命名拼图",
        "items": items,
        "settings": normalize_settings(group.get("settings")),
        "createdAt": int(group.get("createdAt") or 0),
        "updatedAt": int(group.get("updatedAt") or 0),
        "imageUrl": f"/api/collage/groups/{group_id}/image?v={image_mtime}" if image_mtime else "",
        "downloadUrl": f"/api/collage/groups/{group_id}/download" if image_mtime else "",
        "imageMtime": image_mtime,
    }


def serialize_item(item: dict[str, Any]) -> dict[str, Any]:
    path = str(item.get("path") or "")
    return {
        "id": str(item.get("id") or ""),
        "path": path,
        "name": item.get("name") or Path(path).name,
        "mtime": int(item.get("mtime") or 0),
        "width": int(item.get("width") or 0),
        "height": int(item.get("height") or 0),
        "x": int(item.get("x") or 0),
        "y": int(item.get("y") or 0),
        "w": int(item.get("w") or 0),
        "h": int(item.get("h") or 0),
        "cropX": round(clamp_number(item.get("cropX"), 0, 100, 50), 1),
        "cropY": round(clamp_number(item.get("cropY"), 0, 100, 50), 1),
        "thumbUrl": thumb_url(path, "small") if path else "",
        "imageUrl": image_url(path) if path else "",
    }


def serialize_pool(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [serialize_pool_item(item) for item in items if isinstance(item, dict) and item.get("path")]


def serialize_pool_item(item: dict[str, Any]) -> dict[str, Any]:
    path = str(item.get("path") or "")
    return {
        "path": path,
        "name": item.get("name") or Path(path).name,
        "mtime": int(item.get("mtime") or 0),
        "width": int(item.get("width") or 0),
        "height": int(item.get("height") or 0),
        "addedAt": int(item.get("addedAt") or 0),
        "thumbUrl": thumb_url(path, "small") if path else "",
        "imageUrl": image_url(path) if path else "",
    }


def parent_rel(value: str) -> str:
    if not value:
        return ""
    parent = Path(value).parent.as_posix()
    return "" if parent == "." else parent


def next_group_name(groups: list[dict[str, Any]]) -> str:
    return f"拼图 {len(groups) + 1}"


def safe_filename(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "._- " else "_" for char in value).strip()
    return cleaned or "collage"
