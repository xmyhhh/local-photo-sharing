from __future__ import annotations

import json
import random
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
    if services.login_background_provider is not None:
        services.login_background_provider.ensure(async_rebuild=True)


def on_disable(services: AppServices) -> None:
    if services.login_background_provider is not None:
        services.login_background_provider.clear()


class LoginPhotoWallProvider:
    def __init__(self, services: AppServices) -> None:
        self.services = services
        self.rebuild_lock = Lock()

    def gallery(self, limit: int = 36) -> dict:
        self.ensure(limit=limit, async_rebuild=True)
        return {"mode": self.services.auth.login_background_mode, "photos": self.services.login_background_items[:limit]}

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

        def run() -> None:
            try:
                self.rebuild(cache_key, limit)
            finally:
                with self.services.login_background_lock:
                    self.services.login_background_refreshing = False

        Thread(target=run, name="login-photo-wall-cache", daemon=True).start()

    def rebuild(self, cache_key: str, limit: int = 36) -> None:
        with self.rebuild_lock:
            candidates = self.candidate_paths()
            random.shuffle(candidates)
            selected = candidates[: max(1, min(limit, 60))]
            next_cache: dict[str, bytes] = {}
            next_items: list[dict[str, str]] = []
            manifest_items: list[dict[str, object]] = []
            LOGIN_BACKGROUND_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            for rooted in selected:
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
            with self.services.login_background_lock:
                self.services.login_background_cache.clear()
                self.services.login_background_cache.update(next_cache)
                self.services.login_background_items = next_items
                self.services.login_background_cache_key = cache_key if next_items else ""
            write_login_background_manifest({"cacheKey": cache_key, "items": manifest_items})

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

    def candidate_paths(self) -> list[str]:
        mode = self.services.auth.login_background_mode
        if mode == "rated":
            return self.rated_candidates()
        if mode == "folder":
            return self.folder_candidates()
        return []

    def rated_candidates(self) -> list[str]:
        candidates: list[str] = []
        for root_id, root_services in self.services.root_services.items():
            root_services.rating_index.ensure_folder_async(root_services.root)
            for path in iter_limited_photos(root_services.root, 900):
                rel = normalize_rel_path(path.relative_to(root_services.root).as_posix())
                rating = root_services.ratings.get_override(rel)
                if rating is None:
                    rating = root_services.rating_index.get(rel) or 0
                if rating > 0:
                    candidates.append(join_rooted(root_id, rel))
        return candidates

    def folder_candidates(self) -> list[str]:
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
            candidates.extend(join_rooted(root_id, path.relative_to(root_services.root).as_posix()) for path in iter_limited_photos(folder, 900))
        return candidates


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
