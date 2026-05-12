from __future__ import annotations

import random
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from typing import Any

from flask import Flask, abort, jsonify, request

from core.photo_share.constants import CPU_COUNT, PHOTO_EXTENSIONS, RATINGS_FILE, THUMBNAIL_DIR
from core.photo_share.context import AppServices, RootServices
from core.photo_share.paths import image_url, join_rooted_path, parse_rooted_path, preview_url, resolve_folder, thumb_url, to_relative
from core.photo_share.routes.gallery import _root_services

PLUGIN_NAME = "dynamic_screensaver"
MAX_RESULTS = 800
MAX_SCAN_FILES = 300_000
WARMUP_MODE = "xlarge"
WARMUP_WORKERS = min(8, max(2, CPU_COUNT))
READY_CACHE_SECONDS = 6 * 60 * 60

_warmup_lock = Lock()
_warmup_executor = ThreadPoolExecutor(max_workers=WARMUP_WORKERS, thread_name_prefix="dynamic-screensaver-warmup")
_warmup_tasks: dict[str, dict[str, Any]] = {}
_warmup_futures: dict[str, Any] = {}

PLUGIN = {
    "title": "动态屏保",
    "description": "本机空闲后自动轮播有评分照片，可按目录和最低星级筛选。",
    "static_dir": "static",
    "scripts": ["dynamic_screensaver.js"],
    "styles": ["dynamic_screensaver.css"],
    "components": [
        {
            "id": "dynamic_screensaver.open",
            "title": "动态屏保",
            "description": "本机空闲一段时间后启动照片轮播，不影响其他设备。",
            "capabilities": [
                {"type": "background_service", "operations": ["local_idle_watch", "slideshow"]},
                {"type": "function", "operations": ["configure", "list_rated_photos"]},
            ],
            "triggers": [],
            "surfaces": [
                {
                    "type": "settings_page",
                    "id": "dynamic_screensaver.settings",
                    "label": "动态屏保",
                    "title": "动态屏保",
                    "kicker": "本机",
                    "description": "配置当前浏览器的空闲启动和照片筛选条件。",
                },
                {"type": "headless", "id": "dynamicScreensaverIdleWatch"},
            ],
        }
    ],
}


def register(app: Flask, services: AppServices) -> None:
    @app.get("/api/dynamic-screensaver/photos")
    def dynamic_screensaver_photos():
        if PLUGIN_NAME not in services.enabled_plugins:
            abort(404)
        folder = request.args.get("folder", "").strip()
        min_rating = parse_rating(request.args.get("minRating"))
        limit = parse_limit(request.args.get("limit"))
        task = ensure_warmup_task(services, folder, min_rating, limit)
        cached = cached_task_photos(task, limit)
        if cached:
            random.shuffle(cached)
        return jsonify({
            "folder": folder,
            "minRating": min_rating,
            "count": task.get("matched", len(cached)),
            "scanned": task.get("scanned", 0),
            "photos": cached[:limit],
            "truncated": bool(task.get("truncated", False)) or len(cached) > limit,
            "warmup": task_status_payload(task),
        })

    @app.post("/api/dynamic-screensaver/warmup")
    def dynamic_screensaver_warmup():
        if PLUGIN_NAME not in services.enabled_plugins:
            abort(404)
        data = request.get_json(silent=True) or {}
        folder = str(data.get("folder", "")).strip()
        min_rating = parse_rating(str(data.get("minRating", "1")))
        limit = parse_limit(str(data.get("limit", "360")))
        task = ensure_warmup_task(services, folder, min_rating, limit, force=bool(data.get("force", False)))
        return jsonify(task_status_payload(task))

    @app.get("/api/dynamic-screensaver/warmup")
    def dynamic_screensaver_warmup_status():
        if PLUGIN_NAME not in services.enabled_plugins:
            abort(404)
        folder = request.args.get("folder", "").strip()
        min_rating = parse_rating(request.args.get("minRating"))
        limit = parse_limit(request.args.get("limit"))
        task = get_warmup_task(folder, min_rating, limit)
        if task is None:
            return jsonify({
                "state": "idle",
                "folder": folder,
                "minRating": min_rating,
                "limit": limit,
                "scanned": 0,
                "matched": 0,
                "prepared": 0,
                "failed": 0,
                "progress": 0,
                "truncated": False,
                "error": "",
            })
        return jsonify(task_status_payload(task))


def parse_rating(value: str | None) -> int:
    try:
        rating = int(value or "1")
    except ValueError:
        rating = 1
    return max(1, min(5, rating))


def parse_limit(value: str | None) -> int:
    try:
        limit = int(value or "240")
    except ValueError:
        limit = 240
    return max(20, min(MAX_RESULTS, limit))


def warmup_key(folder: str, min_rating: int, limit: int) -> str:
    return f"{folder}|{min_rating}|{limit}"


def get_warmup_task(folder: str, min_rating: int, limit: int) -> dict[str, Any] | None:
    key = warmup_key(folder, min_rating, limit)
    with _warmup_lock:
        return _warmup_tasks.get(key)


def ensure_warmup_task(
    services: AppServices,
    folder: str,
    min_rating: int,
    limit: int,
    *,
    force: bool = False,
) -> dict[str, Any]:
    key = warmup_key(folder, min_rating, limit)
    now = time.time()
    with _warmup_lock:
        existing = _warmup_tasks.get(key)
        if existing and not force:
            state = existing.get("state")
            if state in {"running", "queued"}:
                return existing
            if state == "ready" and now - float(existing.get("finishedAt") or 0) < READY_CACHE_SECONDS:
                return existing
        task = {
            "key": key,
            "state": "queued",
            "folder": folder,
            "minRating": min_rating,
            "limit": limit,
            "scanned": 0,
            "matched": 0,
            "prepared": 0,
            "failed": 0,
            "photos": [],
            "error": "",
            "startedAt": now,
            "finishedAt": 0,
            "truncated": False,
        }
        _warmup_tasks[key] = task
        _warmup_futures[key] = _warmup_executor.submit(run_warmup_task, services, task)
        return task


def cached_task_photos(task: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    with _warmup_lock:
        photos = list(task.get("photos") or [])
        state = task.get("state")
    if state not in {"ready", "running", "queued"}:
        return []
    return photos[:limit]


def task_status_payload(task: dict[str, Any]) -> dict[str, Any]:
    with _warmup_lock:
        total = int(task.get("matched") or 0)
        prepared = int(task.get("prepared") or 0)
        failed = int(task.get("failed") or 0)
        progress_total = max(total, prepared + failed, 1)
        return {
            "state": task.get("state", "idle"),
            "folder": task.get("folder", ""),
            "minRating": task.get("minRating", 1),
            "limit": task.get("limit", 0),
            "scanned": int(task.get("scanned") or 0),
            "matched": total,
            "prepared": prepared,
            "failed": failed,
            "progress": min(100, round((prepared + failed) * 100 / progress_total)),
            "truncated": bool(task.get("truncated", False)),
            "error": task.get("error", ""),
        }


def get_backend_tasks(services: AppServices) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    with _warmup_lock:
        snapshots = [dict(task) for task in _warmup_tasks.values()]
    for task in snapshots:
        state = str(task.get("state") or "")
        if state not in {"queued", "running", "error"}:
            continue
        total = int(task.get("matched") or 0)
        prepared = int(task.get("prepared") or 0)
        failed = int(task.get("failed") or 0)
        progress_total = max(total, prepared + failed, 1)
        tasks.append({
            "id": f"screensaver_warmup.{task.get('key', '')}",
            "title": "动态屏保照片准备",
            "detail": str(task.get("folder") or "全部照片"),
            "state": state,
            "progress": min(1.0, (prepared + failed) / progress_total),
            "completed": prepared + failed,
            "total": total or None,
            "error": str(task.get("error") or ""),
            "meta": {
                "scanned": int(task.get("scanned") or 0),
                "matched": total,
                "prepared": prepared,
                "failed": failed,
                "minRating": int(task.get("minRating") or 1),
            },
        })
    return tasks


def run_warmup_task(services: AppServices, task: dict[str, Any]) -> None:
    update_task(task, state="running", startedAt=time.time())
    try:
        roots = resolve_candidate_roots(services, str(task["folder"]))
        limit = int(task["limit"])
        min_rating = int(task["minRating"])
        photos: list[dict[str, Any]] = []
        seen_paths: set[str] = set()
        scanned = 0

        for root_id, root_services, folder_path in roots:
            for path in iter_photo_files(folder_path):
                scanned += 1
                if scanned > MAX_SCAN_FILES:
                    update_task(task, truncated=True)
                    break
                rel = to_relative(root_services.root, path)
                rating = photo_rating(root_services, rel, path)
                if rating < min_rating:
                    if scanned % 200 == 0:
                        update_task(task, scanned=scanned)
                    continue
                rooted = join_rooted_path(root_id, rel)
                if rooted in seen_paths:
                    continue
                seen_paths.add(rooted)
                update_task(task, scanned=scanned, matched=len(seen_paths))
                prepared = warmup_screensaver_cache(root_services, path)
                stat = path.stat()
                photo = {
                    "name": path.name,
                    "path": rooted,
                    "folder": str(Path(rooted).parent).replace("\\", "/"),
                    "rating": rating,
                    "mtime": int(stat.st_mtime),
                    "imageUrl": image_url(rooted),
                    "previewUrl": preview_url(rooted),
                    "thumbUrl": thumb_url(rooted, WARMUP_MODE),
                    "preparedUrl": thumb_url(rooted, WARMUP_MODE),
                    "browserRenderable": path.suffix.lower() in {".jpg", ".jpeg"},
                    "prepared": prepared,
                }
                photos.append(photo)
                if prepared:
                    increment_task(task, "prepared")
                else:
                    increment_task(task, "failed")
                update_task(task, photos=photos.copy())
                if len(seen_paths) >= limit:
                    update_task(task, truncated=True)
                    break
            if scanned > MAX_SCAN_FILES or len(seen_paths) >= limit:
                break

        random.shuffle(photos)
        update_task(task, photos=photos, state="ready", finishedAt=time.time())
    except Exception as exc:
        update_task(task, state="error", error=str(exc), finishedAt=time.time())


def warmup_screensaver_cache(root_services: RootServices, path: Path) -> bool:
    store = root_services.thumbnails.get(WARMUP_MODE) or root_services.default_thumbnails
    if store.get_ready(path, validate=True) is not None:
        return True
    return store.warmup_one(path)


def update_task(task: dict[str, Any], **values: Any) -> None:
    with _warmup_lock:
        task.update(values)


def increment_task(task: dict[str, Any], field: str, amount: int = 1) -> None:
    with _warmup_lock:
        task[field] = int(task.get(field) or 0) + amount


def resolve_candidate_roots(services: AppServices, folder: str) -> list[tuple[str, RootServices, Path]]:
    if folder:
        root_id, rel = parse_rooted_path(folder)
        root_services = _root_services(services, root_id)
        return [(root_id, root_services, resolve_folder(root_services.root, rel))]
    return [
        (root_id, root_services, root_services.root)
        for root_id, root_services in services.root_services.items()
    ]


def iter_photo_files(folder_path: Path):
    stack = [folder_path]
    while stack:
        folder = stack.pop()
        try:
            children = sorted(folder.iterdir(), key=lambda item: item.name.lower())
        except OSError:
            continue
        for child in children:
            if child.name in {RATINGS_FILE, THUMBNAIL_DIR}:
                continue
            try:
                if child.is_dir():
                    stack.append(child)
                elif child.is_file() and child.suffix.lower() in PHOTO_EXTENSIONS:
                    yield child
            except OSError:
                continue


def photo_rating(root_services: RootServices, rel: str, path: Path) -> int:
    override = root_services.ratings.get_override(rel)
    if override is not None:
        return override
    indexed = root_services.rating_index.get(rel)
    if indexed is not None:
        return indexed
    if root_services.metadata.is_ready(path):
        return root_services.metadata.get_rating_ready(path)
    return root_services.rating_index.ensure_photo_quick(path)
