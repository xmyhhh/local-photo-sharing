from __future__ import annotations

import json
import random
import time
from io import BytesIO
from pathlib import Path
from threading import Lock, Thread

from flask import Flask
from PIL import Image, ImageOps

from core.photo_share.auth import join_rooted, normalize_rooted_path
from core.photo_share.constants import CACHE_DIR, PHOTO_EXTENSIONS
from core.photo_share.context import AppServices
from core.photo_share.paths import hash_text, normalize_rel_path, parse_rooted_path, quote_path

PLUGIN_NAME = "login_photo_wall"
LOGIN_BACKGROUND_CACHE_DIR = CACHE_DIR / "login_backgrounds"
LOGIN_BACKGROUND_MANIFEST = LOGIN_BACKGROUND_CACHE_DIR / "manifest.json"
LOGIN_BACKGROUND_REBUILD_AFTER_SECONDS = 30 * 60

PLUGIN = {
    "title": "登录页照片墙",
    "description": "为登录页生成照片马赛克背景。会扫描图库并构建小图缓存，低性能服务器可禁用。",
    "components": [
        {
            "id": "login_photo_wall.background",
            "title": "登录页照片墙",
            "description": "登录页照片马赛克背景和对应服务端缓存。",
            "capabilities": [
                {"type": "background_service", "operations": ["scan_login_backgrounds", "build_login_background_cache"]},
            ],
            "triggers": [],
            "surfaces": [
                {"type": "headless", "id": "loginPhotoWallBackground"},
            ],
        }
    ],
}


def register(app: Flask, services: AppServices) -> None:
    services.login_background_provider = LoginPhotoWallProvider(services)


def on_enable(services: AppServices) -> None:
    if services.login_background_provider is not None and services.auth.login_background_mode != "none":
        services.login_background_provider.restore(services.login_background_provider.config_key())


def on_disable(services: AppServices) -> None:
    if services.login_background_provider is not None:
        services.login_background_provider.clear()


def get_backend_tasks(services: AppServices) -> list[dict[str, object]]:
    provider = services.login_background_provider
    if provider is None:
        return []
    task = provider.task_snapshot()
    state = str(task.get("state") or "idle")
    if state not in {"queued", "running", "scanning", "error"}:
        return []
    total = int(task.get("total") or 0)
    prepared = int(task.get("prepared") or 0)
    scanned = int(task.get("scanned") or 0)
    progress = None
    if total > 0:
        progress = min(1.0, max(0.0, prepared / total))
    return [{
        "id": "login_background_cache",
        "title": "登录背景照片墙缓存",
        "detail": services.auth.login_background_folder or "公开相册 / 评分图集",
        "state": state,
        "progress": progress,
        "progressMode": "percent" if progress is not None else "activity",
        "completed": prepared,
        "total": total or None,
        "error": str(task.get("error") or ""),
        "meta": {
            "scanned": scanned,
            "cacheKey": str(task.get("cacheKey") or ""),
        },
    }]


class LoginPhotoWallProvider:
    def __init__(self, services: AppServices) -> None:
        self.services = services
        self.rebuild_lock = Lock()
        self.task: dict[str, object] = {
            "state": "idle",
            "cacheKey": "",
            "scanned": 0,
            "total": 0,
            "prepared": 0,
            "error": "",
            "startedAt": 0.0,
            "finishedAt": 0.0,
        }

    def gallery(self, limit: int = 36) -> dict:
        self.ensure(limit=limit, async_rebuild=True)
        with self.services.login_background_lock:
            items = list(self.services.login_background_items)
        random.shuffle(items)
        return {"mode": self.services.auth.login_background_mode, "photos": items[:limit]}

    def clear(self) -> None:
        with self.services.login_background_lock:
            self.services.login_background_cache.clear()
            self.services.login_background_items = []
            self.services.login_background_cache_key = ""

    def ensure(
        self,
        limit: int = 36,
        force: bool = False,
        async_rebuild: bool = False,
    ) -> None:
        if self.services.auth.login_background_mode == "none":
            self.clear()
            return
        cache_key = self.config_key()
        with self.services.login_background_lock:
            if not force and self.services.login_background_cache_key == cache_key and self.services.login_background_items:
                if not self.cache_is_stale():
                    return
        if not force and self.restore(cache_key):
            return
        if async_rebuild:
            self.schedule_rebuild(cache_key, limit)
            return
        self.rebuild(cache_key, limit)

    def schedule_rebuild(self, cache_key: str, limit: int = 36) -> None:
        with self.services.login_background_lock:
            if self.services.login_background_refreshing:
                return
            self.services.login_background_refreshing = True
        self.update_task(state="queued", cacheKey=cache_key, scanned=0, total=0, prepared=0, error="", startedAt=time.time(), finishedAt=0.0)

        def run() -> None:
            try:
                self.rebuild(cache_key, limit)
            except Exception as exc:
                self.update_task(state="error", error=str(exc), finishedAt=time.time())
            finally:
                with self.services.login_background_lock:
                    self.services.login_background_refreshing = False

        Thread(target=run, name="login-photo-wall-cache", daemon=True).start()

    def rebuild(self, cache_key: str, limit: int = 36) -> None:
        with self.rebuild_lock:
            self.update_task(state="scanning", cacheKey=cache_key, scanned=0, total=0, prepared=0, error="", startedAt=time.time(), finishedAt=0.0)
            candidates = self.candidate_paths(max(900, limit * 12))
            selected = choose_photo_wall_candidates(candidates, max(1, min(limit, 60)))
            self.update_task(state="running", total=len(selected))
            next_cache: dict[str, bytes] = {}
            next_items: list[dict[str, str]] = []
            manifest_items: list[dict[str, object]] = []
            LOGIN_BACKGROUND_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            for index, rooted in enumerate(selected, start=1):
                self.update_task(scanned=index)
                source = self.source_info(rooted)
                if source is None:
                    continue
                key = hash_text(f"{rooted}:{source['mtime']}:{source['size']}")
                cache_path = LOGIN_BACKGROUND_CACHE_DIR / f"{key}.jpg"
                data = read_cache_file(cache_path)
                if data is None:
                    data = self.build_jpeg(rooted)
                    if data is None:
                        continue
                    write_cache_file(cache_path, data)
                url_key = quote_path(key)
                item = {
                    "path": rooted,
                    "thumbUrl": f"/api/auth/background-memory/{url_key}",
                    "key": url_key,
                    "cacheKey": cache_key,
                }
                next_cache[url_key] = data
                next_items.append(item)
                manifest_items.append({**item, "file": cache_path.name, "mtime": source["mtime"], "size": source["size"]})
                self.update_task(prepared=len(next_items))
            with self.services.login_background_lock:
                self.services.login_background_cache.clear()
                self.services.login_background_cache.update(next_cache)
                self.services.login_background_items = next_items
                self.services.login_background_cache_key = cache_key if next_items else ""
            write_login_background_manifest({"cacheKey": cache_key, "createdAt": int(time.time()), "items": manifest_items})
            self.update_task(state="idle", prepared=len(next_items), finishedAt=time.time())

    def restore(self, cache_key: str) -> bool:
        manifest = read_login_background_manifest()
        if manifest.get("cacheKey") != cache_key:
            return False
        next_cache: dict[str, bytes] = {}
        next_items: list[dict[str, str]] = []
        for item in manifest.get("items", []):
            if not isinstance(item, dict):
                continue
            rooted = str(item.get("path") or "")
            source = self.source_info(rooted)
            if source is None or int(item.get("mtime") or -1) != source["mtime"] or int(item.get("size") or -1) != source["size"]:
                return False
            key = str(item.get("key") or "")
            file_name = str(item.get("file") or "")
            if not key or not file_name:
                return False
            data = read_cache_file(LOGIN_BACKGROUND_CACHE_DIR / file_name)
            if data is None:
                return False
            next_cache[key] = data
            next_items.append({
                "path": rooted,
                "thumbUrl": str(item.get("thumbUrl") or f"/api/auth/background-memory/{key}"),
                "key": key,
                "cacheKey": cache_key,
            })
        if not next_items:
            return False
        with self.services.login_background_lock:
            self.services.login_background_cache.clear()
            self.services.login_background_cache.update(next_cache)
            self.services.login_background_items = next_items
            self.services.login_background_cache_key = cache_key
        return True

    def config_key(self) -> str:
        parts = [
            self.services.auth.login_background_mode,
            self.services.auth.login_background_folder,
            *sorted(self.services.auth.public_albums),
        ]
        return hash_text("|".join(parts))

    def cache_is_stale(self) -> bool:
        manifest = read_login_background_manifest()
        created_at = float(manifest.get("createdAt") or 0)
        return created_at > 0 and time.time() - created_at > LOGIN_BACKGROUND_REBUILD_AFTER_SECONDS

    def update_task(self, **values: object) -> None:
        with self.services.login_background_lock:
            self.task.update(values)

    def task_snapshot(self) -> dict[str, object]:
        with self.services.login_background_lock:
            return dict(self.task)

    def source_info(self, rooted: str) -> dict[str, int] | None:
        try:
            root_id, rel = parse_rooted_path(rooted)
            root_services = self.services.root_services[root_id]
            path = (root_services.root / rel).resolve()
            path.relative_to(root_services.root)
            stat = path.stat()
            if not path.is_file() or path.suffix.lower() not in PHOTO_EXTENSIONS:
                return None
            return {"mtime": int(stat.st_mtime), "size": int(stat.st_size)}
        except Exception:
            return None

    def build_jpeg(self, rooted: str) -> bytes | None:
        try:
            root_id, rel = parse_rooted_path(rooted)
            root_services = self.services.root_services[root_id]
            path = (root_services.root / rel).resolve()
            path.relative_to(root_services.root)
            if path.suffix.lower() not in PHOTO_EXTENSIONS:
                return None
            with Image.open(path) as image:
                output = ImageOps.exif_transpose(image)
                output.thumbnail((520, 520))
                if output.mode not in {"RGB", "L"}:
                    output = output.convert("RGB")
                buffer = BytesIO()
                output.save(buffer, format="JPEG", quality=70, optimize=True)
                return buffer.getvalue()
        except Exception:
            return None

    def candidate_paths(self, limit: int = 900) -> list[str]:
        mode = self.services.auth.login_background_mode
        if mode == "rated":
            return self.rated_candidates(limit)
        if mode == "folder":
            return self.folder_candidates(limit)
        return []

    def rated_candidates(self, limit: int = 900) -> list[str]:
        candidates: list[str] = []
        for root_id, root_services in self.services.root_services.items():
            root_services.rating_index.ensure_folder_async(root_services.root)
            for path in iter_limited_photos(root_services.root, limit):
                rel = normalize_rel_path(path.relative_to(root_services.root).as_posix())
                rating = root_services.ratings.get_override(rel)
                if rating is None:
                    rating = root_services.rating_index.get(rel) or 0
                if rating > 0:
                    candidates.append(join_rooted(root_id, rel))
        return candidates

    def folder_candidates(self, limit: int = 900) -> list[str]:
        folders = [self.services.auth.login_background_folder] if self.services.auth.login_background_folder else sorted(self.services.auth.public_albums)
        candidates: list[str] = []
        for item in folders:
            try:
                root_id, rel = parse_rooted_path(normalize_rooted_path(item))
            except Exception:
                continue
            root_services = self.services.root_services.get(root_id)
            if root_services is None:
                continue
            folder = (root_services.root / rel).resolve()
            try:
                folder.relative_to(root_services.root)
            except ValueError:
                continue
            if not folder.is_dir():
                continue
            candidates.extend(join_rooted(root_id, path.relative_to(root_services.root).as_posix()) for path in iter_limited_photos(folder, limit))
        return candidates


def choose_photo_wall_candidates(candidates: list[str], count: int) -> list[str]:
    if len(candidates) <= count:
        random.shuffle(candidates)
        return candidates
    seed = random.SystemRandom().randint(0, 2**31 - 1)
    scored = [
        (hash_text(f"{seed}:{index}:{path}"), path)
        for index, path in enumerate(candidates)
    ]
    scored.sort(key=lambda item: item[0])
    return [path for _, path in scored[:count]]


def read_cache_file(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


def write_cache_file(path: Path, data: bytes) -> None:
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_bytes(data)
    tmp_path.replace(path)


def read_login_background_manifest() -> dict:
    try:
        data = json.loads(LOGIN_BACKGROUND_MANIFEST.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_login_background_manifest(data: dict) -> None:
    LOGIN_BACKGROUND_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = LOGIN_BACKGROUND_MANIFEST.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(LOGIN_BACKGROUND_MANIFEST)


def iter_limited_photos(folder: Path, limit: int):
    seen = 0
    stack = [folder]
    while stack and seen < limit:
        current = stack.pop()
        try:
            children = list(current.iterdir())
        except OSError:
            continue
        random.shuffle(children)
        for child in children:
            if seen >= limit:
                break
            try:
                if child.is_dir():
                    stack.append(child)
                elif child.is_file() and child.suffix.lower() in PHOTO_EXTENSIONS:
                    seen += 1
                    yield child
            except OSError:
                continue
