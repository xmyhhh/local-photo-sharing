from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock, Thread
from typing import Any

from flask import Flask, abort, jsonify, request, send_file
from PIL import Image, ImageOps, ImageStat
import piexif

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
JPG_EXTENSIONS = {".jpg", ".jpeg"}
RATINGS_FILE = ".photo_share_ratings.json"
THUMBNAIL_DIR = ".photo_share_thumbs"
CACHE_DIR = APP_DIR / ".photo_share_cache"
CPU_COUNT = os.cpu_count() or 1
THUMBNAIL_WORKERS = min(8, max(2, CPU_COUNT))
METADATA_WORKERS = min(4, max(2, CPU_COUNT // 2))
THUMB_CACHE_QUEUE_LIMIT = 50
PREVIEW_CACHE_QUEUE_LIMIT = 25
FILTER_WAIT_SECONDS = 0.8
DEFAULT_THUMBNAIL_SIZE = 360
DEFAULT_THUMBNAIL_QUALITY = 74
DEFAULT_PREVIEW_SIZE = 2560
DEFAULT_PREVIEW_QUALITY = 88
THUMBNAIL_MODES = {
    "small": {"size": 260, "quality": 68},
    "medium": {"size": DEFAULT_THUMBNAIL_SIZE, "quality": DEFAULT_THUMBNAIL_QUALITY},
    "large": {"size": 640, "quality": 84},
}
DEFAULT_THUMBNAIL_MODE = "medium"
BRACKET_SCAN_LIMIT = 500
DEFAULT_CONFIG_FILE = APP_DIR / "config.json"
DEFAULT_CONFIG = {
    "photo_folder": "D:/your/photo/folder",
    "host": "0.0.0.0",
    "port": 8000,
    "thumbnail_size": DEFAULT_THUMBNAIL_SIZE,
    "thumbnail_quality": DEFAULT_THUMBNAIL_QUALITY,
    "preview_size": DEFAULT_PREVIEW_SIZE,
    "preview_quality": DEFAULT_PREVIEW_QUALITY,
}


def create_app(
    photo_root: Path,
    thumbnail_size: int = DEFAULT_THUMBNAIL_SIZE,
    thumbnail_quality: int = DEFAULT_THUMBNAIL_QUALITY,
    preview_size: int = DEFAULT_PREVIEW_SIZE,
    preview_quality: int = DEFAULT_PREVIEW_QUALITY,
) -> Flask:
    root = photo_root.resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Photo root does not exist or is not a folder: {root}")

    app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")
    ratings = RatingStore(root / RATINGS_FILE)
    cache_root = CACHE_DIR / root_cache_key(root)
    metadata = MetadataStore(root)
    rating_index = RatingIndex(root, ratings, metadata)
    thumbnail_modes = build_thumbnail_modes(thumbnail_size, thumbnail_quality)
    thumbnails = {
        mode: ImageCacheStore(
            root,
            cache_root / f"thumbs_{mode}_{spec['size']}_{spec['quality']}",
            spec["size"],
            spec["quality"],
            f"thumb-{mode}",
            queue_limit=THUMB_CACHE_QUEUE_LIMIT,
        )
        for mode, spec in thumbnail_modes.items()
    }
    default_thumbnails = thumbnails[DEFAULT_THUMBNAIL_MODE]
    previews = ImageCacheStore(
        root,
        cache_root / f"previews_{preview_size}_{preview_quality}",
        preview_size,
        preview_quality,
        "preview",
        queue_limit=PREVIEW_CACHE_QUEUE_LIMIT,
    )

    @app.get("/")
    def index():
        return send_file(STATIC_DIR / "index.html")

    @app.get("/api/config")
    def config():
        return jsonify({"root": str(root), "allowDelete": True})

    @app.get("/api/photos")
    def photos():
        folder = request.args.get("folder", "")
        folder_path = resolve_folder(root, folder)
        filters = PhotoFilters.from_request(request.args)
        entries: list[dict[str, Any]] = []
        pending_entries: list[dict[str, Any]] = []
        indexing = False

        if filters.needs_rating:
            rating_index.index_folder_budget(folder_path, FILTER_WAIT_SECONDS)
            indexing = not rating_index.is_folder_ready(folder_path)

        for child in sorted(folder_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if child.name in {RATINGS_FILE, THUMBNAIL_DIR}:
                continue
            rel = to_relative(root, child)
            if child.is_dir():
                entries.append({"type": "folder", "name": child.name, "path": rel})
            elif child.suffix.lower() in JPG_EXTENSIONS:
                stat = child.stat()
                rating_override = ratings.get_override(rel)
                if rating_override is None:
                    rating = metadata.get_rating_ready(child)
                    rating_pending = not metadata.is_ready(child)
                    if filters.needs_rating:
                        indexed_rating = rating_index.get(to_relative(root, child))
                        if indexed_rating is not None:
                            rating = indexed_rating
                            rating_pending = False
                else:
                    rating = rating_override
                    rating_pending = False
                entry = {
                    "type": "photo",
                    "name": child.name,
                    "path": rel,
                    "size": stat.st_size,
                    "mtime": int(stat.st_mtime),
                    "rating": rating,
                    "ratingPending": rating_pending,
                }
                if filters.needs_rating and rating_pending:
                    continue
                if not filters.matches_photo(rating, int(stat.st_mtime)):
                    continue
                entries.append(entry)

        parent = ""
        if folder:
            parent_path = Path(folder).parent
            parent = "" if str(parent_path) == "." else as_posix(parent_path)

        if filters.needs_rating and indexing:
            rating_index.ensure_folder_async(folder_path)

        return jsonify({
            "folder": folder,
            "parent": parent,
            "entries": entries,
            "pendingEntries": pending_entries,
            "indexing": indexing,
        })

    @app.get("/api/bracket-detection")
    def bracket_detection():
        folder = request.args.get("folder", "")
        folder_path = resolve_folder(root, folder)
        result = detect_exposure_brackets(root, folder_path, default_thumbnails)
        return jsonify({"folder": folder, **result})

    @app.get("/api/image/<path:photo_path>")
    def image(photo_path: str):
        path = resolve_photo(root, photo_path)
        return send_cached_file(path, mimetype=mimetypes.guess_type(path.name)[0] or "image/jpeg")

    @app.get("/api/preview/<path:photo_path>")
    def preview(photo_path: str):
        path = resolve_photo(root, photo_path)
        preview_path = previews.get_ready(path)
        if preview_path is None:
            previews.ensure(path)
            return jsonify({"status": "processing", "url": preview_url(photo_path)}), 202
        return send_cached_file(preview_path, mimetype="image/jpeg")

    @app.get("/api/preview-status/<path:photo_path>")
    def preview_status(photo_path: str):
        path = resolve_photo(root, photo_path)
        error = previews.get_error(path)
        if error:
            return jsonify({"status": "error", "url": image_url(photo_path), "error": error}), 500
        preview_path = previews.get_ready(path)
        if preview_path is not None:
            return jsonify({"status": "ready", "url": preview_url(photo_path)})
        queued = previews.ensure(path)
        return jsonify({"status": "queued" if queued else "processing", "url": preview_url(photo_path)}), 202

    @app.get("/api/download/<path:photo_path>")
    def download(photo_path: str):
        path = resolve_photo(root, photo_path)
        return send_cached_file(
            path,
            mimetype=mimetypes.guess_type(path.name)[0] or "image/jpeg",
            as_attachment=True,
            download_name=path.name,
        )

    @app.get("/api/thumb/<path:photo_path>")
    def thumbnail(photo_path: str):
        path = resolve_photo(root, photo_path)
        mode = get_thumbnail_mode(request.args.get("mode"))
        thumb_store = thumbnails[mode]
        thumb = thumb_store.get_ready(path)
        if thumb is None:
            thumb_store.ensure(path)
            return jsonify({"status": "processing", "url": thumb_url(photo_path, mode)}), 202
        return send_cached_file(thumb, mimetype="image/jpeg")

    @app.get("/api/thumb-status/<path:photo_path>")
    def thumbnail_status(photo_path: str):
        path = resolve_photo(root, photo_path)
        mode = get_thumbnail_mode(request.args.get("mode"))
        thumb_store = thumbnails[mode]
        error = thumb_store.get_error(path)
        if error:
            return jsonify({"status": "error", "url": image_url(photo_path), "error": error}), 500
        thumb = thumb_store.get_ready(path)
        if thumb is not None:
            return jsonify({"status": "ready", "url": thumb_url(photo_path, mode)})
        queued = thumb_store.ensure(path)
        return jsonify({"status": "queued" if queued else "processing", "url": thumb_url(photo_path, mode)}), 202

    @app.get("/api/rating-status/<path:photo_path>")
    def rating_status(photo_path: str):
        path = resolve_photo(root, photo_path)
        rel = normalize_rel_path(photo_path)
        rating_override = ratings.get_override(rel)
        if rating_override is not None:
            return jsonify({"status": "ready", "rating": rating_override, "source": "user"})
        error = metadata.get_error(path)
        if error:
            return jsonify({"status": "error", "rating": 0, "error": error}), 500
        if metadata.is_ready(path):
            return jsonify({"status": "ready", "rating": metadata.get_rating_ready(path), "source": "embedded"})
        queued = metadata.ensure(path)
        return jsonify({"status": "queued" if queued else "processing", "rating": 0}), 202

    @app.post("/api/rating/<path:photo_path>")
    def set_rating(photo_path: str):
        path = resolve_photo(root, photo_path)
        data = request.get_json(silent=True) or {}
        value = data.get("rating")
        if not isinstance(value, int) or value < 0 or value > 5:
            abort(400, "rating must be an integer from 0 to 5")

        rel = normalize_rel_path(photo_path)
        try:
            write_embedded_rating(path, value)
        except Exception as error:
            abort(500, f"failed to write JPEG rating: {error}")
        ratings.set(rel, value)
        metadata.set_ready(path, value)
        rating_index.set(rel, value)
        return jsonify({"path": rel, "rating": ratings.get(rel)})

    @app.delete("/api/photo/<path:photo_path>")
    def delete_photo(photo_path: str):
        path = resolve_photo(root, photo_path)
        rel = to_relative(root, path)
        path.unlink()
        ratings.delete(rel)
        for thumb_store in thumbnails.values():
            thumb_store.delete(path)
        previews.delete(path)
        metadata.delete(path)
        rating_index.delete(rel)
        return jsonify({"deleted": rel})

    return app


class RatingStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = Lock()
        self.data: dict[str, int] = self._load()

    def _load(self) -> dict[str, int]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        clean: dict[str, int] = {}
        for key, value in raw.items():
            try:
                rating = int(value)
            except (TypeError, ValueError):
                continue
            if 0 <= rating <= 5:
                clean[str(key)] = rating
        return clean

    def _save(self) -> None:
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def get(self, rel_path: str) -> int:
        return self.data.get(rel_path, 0)

    def get_override(self, rel_path: str) -> int | None:
        return self.data.get(rel_path)

    def set(self, rel_path: str, value: int) -> None:
        with self.lock:
            self.data[rel_path] = value
            self._save()

    def delete(self, rel_path: str) -> None:
        with self.lock:
            self.data.pop(rel_path, None)
            self._save()


class MetadataStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.lock = Lock()
        self.data: dict[str, dict[str, int]] = {}
        self.errors: dict[str, str] = {}
        self.executor = ThreadPoolExecutor(max_workers=METADATA_WORKERS, thread_name_prefix="metadata")
        self.inflight: set[str] = set()

    def get_rating_ready(self, photo_path: Path) -> int:
        rel = to_relative(self.root, photo_path)
        stat = photo_path.stat()
        cached = self.data.get(rel)
        if cached and cached.get("mtime") == int(stat.st_mtime) and cached.get("size") == stat.st_size:
            return cached.get("rating", 0)
        return 0

    def is_ready(self, photo_path: Path) -> bool:
        rel = to_relative(self.root, photo_path)
        stat = photo_path.stat()
        cached = self.data.get(rel)
        return bool(cached and cached.get("mtime") == int(stat.st_mtime) and cached.get("size") == stat.st_size)

    def get_error(self, photo_path: Path) -> str | None:
        return self.errors.get(self._task_key(photo_path))

    def ensure(self, photo_path: Path) -> bool:
        if self.is_ready(photo_path):
            return False
        task_key = self._task_key(photo_path)
        with self.lock:
            if task_key in self.inflight:
                return False
            self.inflight.add(task_key)
            self.errors.pop(task_key, None)
        self.executor.submit(self._read_with_cleanup, photo_path, task_key)
        return True

    def _read_with_cleanup(self, photo_path: Path, task_key: str) -> None:
        try:
            self._read(photo_path)
        except Exception as exc:
            print(f"Failed to read metadata for {photo_path}: {exc}")
            with self.lock:
                self.errors[task_key] = str(exc)
        finally:
            with self.lock:
                self.inflight.discard(task_key)

    def _read(self, photo_path: Path) -> None:
        if not photo_path.exists():
            return
        rel = to_relative(self.root, photo_path)
        stat = photo_path.stat()
        cached = self.data.get(rel)
        if cached and cached.get("mtime") == int(stat.st_mtime) and cached.get("size") == stat.st_size:
            return
        rating = read_embedded_rating(photo_path)
        self.set_ready(photo_path, rating)

    def set_ready(self, photo_path: Path, rating: int) -> None:
        if not photo_path.exists():
            return
        rel = to_relative(self.root, photo_path)
        stat = photo_path.stat()
        with self.lock:
            self.data[rel] = {
                "mtime": int(stat.st_mtime),
                "size": stat.st_size,
                "rating": rating,
            }

    def delete(self, photo_path: Path) -> None:
        rel = to_relative(self.root, photo_path)
        with self.lock:
            self.data.pop(rel, None)
            self.errors.pop(self._task_key(photo_path), None)

    def _task_key(self, photo_path: Path) -> str:
        stat = photo_path.stat()
        rel = to_relative(self.root, photo_path)
        return f"{rel}:{int(stat.st_mtime)}:{stat.st_size}"


class RatingIndex:
    def __init__(self, root: Path, ratings: RatingStore, metadata: MetadataStore) -> None:
        self.root = root
        self.ratings = ratings
        self.metadata = metadata
        self.lock = Lock()
        self.by_path: dict[str, dict[str, int]] = {}
        self.by_rating: dict[int, set[str]] = {rating: set() for rating in range(0, 6)}
        self.indexed_folders: dict[str, int] = {}
        self.folder_inflight: set[str] = set()
        self.executor = ThreadPoolExecutor(max_workers=METADATA_WORKERS, thread_name_prefix="rating-index")
        self.folder_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rating-index-folder")

    def ensure_folder(self, folder_path: Path) -> None:
        folder_key = to_relative(self.root, folder_path) if folder_path != self.root else ""
        newest = self._folder_signature(folder_path)
        with self.lock:
            if self.indexed_folders.get(folder_key) == newest:
                return

        try:
            photos = [child for child in folder_path.iterdir() if child.suffix.lower() in JPG_EXTENSIONS and child.is_file()]
            list(self.executor.map(self.ensure_photo_quick, photos))
            with self.lock:
                self.indexed_folders[folder_key] = newest
        finally:
            with self.lock:
                self.folder_inflight.discard(folder_key)

    def ensure_folder_async(self, folder_path: Path) -> bool:
        folder_key = to_relative(self.root, folder_path) if folder_path != self.root else ""
        newest = self._folder_signature(folder_path)
        with self.lock:
            if self.indexed_folders.get(folder_key) == newest or folder_key in self.folder_inflight:
                return False
            self.folder_inflight.add(folder_key)
        self.folder_executor.submit(self.ensure_folder, folder_path)
        return True

    def index_folder_budget(self, folder_path: Path, budget: float) -> None:
        folder_key = to_relative(self.root, folder_path) if folder_path != self.root else ""
        newest = self._folder_signature(folder_path)
        with self.lock:
            if self.indexed_folders.get(folder_key) == newest:
                return
        deadline = time.perf_counter() + budget
        complete = True
        for child in sorted(folder_path.iterdir(), key=lambda p: p.name.lower()):
            if child.suffix.lower() not in JPG_EXTENSIONS or not child.is_file():
                continue
            if time.perf_counter() >= deadline:
                complete = False
                break
            self.ensure_photo_quick(child)
        if complete:
            with self.lock:
                self.indexed_folders[folder_key] = newest

    def is_folder_ready(self, folder_path: Path) -> bool:
        folder_key = to_relative(self.root, folder_path) if folder_path != self.root else ""
        newest = self._folder_signature(folder_path)
        with self.lock:
            return self.indexed_folders.get(folder_key) == newest

    def wait_for_folder(self, folder_path: Path, timeout: float) -> bool:
        folder_key = to_relative(self.root, folder_path) if folder_path != self.root else ""
        newest = self._folder_signature(folder_path)
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            with self.lock:
                if self.indexed_folders.get(folder_key) == newest:
                    return True
            time.sleep(0.03)
        with self.lock:
            return self.indexed_folders.get(folder_key) == newest

    def ensure_photo(self, photo_path: Path) -> int:
        rel = to_relative(self.root, photo_path)
        stat = photo_path.stat()
        cached = self.by_path.get(rel)
        if cached and cached.get("mtime") == int(stat.st_mtime) and cached.get("size") == stat.st_size:
            return cached.get("rating", 0)

        override = self.ratings.get_override(rel)
        rating = override if override is not None else read_embedded_rating(photo_path)
        self.set(rel, rating, photo_path)
        self.metadata.set_ready(photo_path, rating)
        return rating

    def ensure_photo_quick(self, photo_path: Path) -> int:
        rel = to_relative(self.root, photo_path)
        stat = photo_path.stat()
        cached = self.by_path.get(rel)
        if cached and cached.get("mtime") == int(stat.st_mtime) and cached.get("size") == stat.st_size:
            return cached.get("rating", 0)

        override = self.ratings.get_override(rel)
        rating = override if override is not None else read_xmp_head_rating(photo_path)
        self.set(rel, rating, photo_path)
        if rating:
            self.metadata.set_ready(photo_path, rating)
        return rating

    def get(self, rel: str) -> int | None:
        cached = self.by_path.get(rel)
        if not cached:
            return None
        return cached.get("rating", 0)

    def set(self, rel: str, rating: int, photo_path: Path | None = None) -> None:
        if photo_path is None:
            photo_path = self.root / rel
        stat = photo_path.stat()
        with self.lock:
            old = self.by_path.get(rel)
            if old:
                self.by_rating.get(old.get("rating", 0), set()).discard(rel)
            self.by_path[rel] = {
                "mtime": int(stat.st_mtime),
                "size": stat.st_size,
                "rating": rating,
            }
            self.by_rating.setdefault(rating, set()).add(rel)

    def delete(self, rel: str) -> None:
        with self.lock:
            old = self.by_path.pop(rel, None)
            if old:
                self.by_rating.get(old.get("rating", 0), set()).discard(rel)

    def _folder_signature(self, folder_path: Path) -> int:
        newest = 0
        for child in folder_path.iterdir():
            if child.suffix.lower() in JPG_EXTENSIONS and child.is_file():
                newest = max(newest, int(child.stat().st_mtime))
        return newest


class ImageCacheStore:
    def __init__(
        self,
        root: Path,
        cache_root: Path,
        size: int,
        quality: int,
        thread_name: str,
        queue_limit: int = THUMB_CACHE_QUEUE_LIMIT,
    ) -> None:
        self.root = root
        self.cache_root = cache_root
        self.size = size
        self.quality = quality
        self.queue_limit = queue_limit
        self.lock = Lock()
        self.queue: list[tuple[Path, str, str]] = []
        self.queued: set[str] = set()
        self.inflight: set[str] = set()
        self.errors: dict[str, str] = {}
        for index in range(THUMBNAIL_WORKERS):
            Thread(target=self._worker_loop, name=f"{thread_name}_{index}", daemon=True).start()

    def get_ready(self, photo_path: Path) -> Path | None:
        rel = to_relative(self.root, photo_path)
        cache_path = self.cache_root / f"{hash_text(rel)}.jpg"
        source_stat = photo_path.stat()

        if (
            cache_path.exists()
            and cache_path.stat().st_mtime >= source_stat.st_mtime
            and cache_path.stat().st_size > 0
        ):
            return cache_path
        return None

    def ensure(self, photo_path: Path) -> bool:
        rel = to_relative(self.root, photo_path)
        task_key = self._task_key(photo_path)
        with self.lock:
            if task_key in self.inflight or task_key in self.queued:
                return False
            self.errors.pop(self._error_key(photo_path), None)
            self.queue.insert(0, (photo_path, rel, task_key))
            self.queued.add(task_key)
            while len(self.queue) > self.queue_limit:
                _, _, dropped_key = self.queue.pop()
                self.queued.discard(dropped_key)
        return True

    def _worker_loop(self) -> None:
        import time

        while True:
            task = self._next_task()
            if task is None:
                time.sleep(0.03)
                continue
            photo_path, rel, task_key = task
            self._generate_with_cleanup(photo_path, rel, task_key)

    def _next_task(self) -> tuple[Path, str, str] | None:
        with self.lock:
            while self.queue:
                photo_path, rel, task_key = self.queue.pop(0)
                self.queued.discard(task_key)
                if task_key in self.inflight:
                    continue
                self.inflight.add(task_key)
                return photo_path, rel, task_key
        return None

    def _generate_with_cleanup(self, photo_path: Path, rel: str, task_key: str) -> None:
        try:
            self._generate(photo_path, rel)
        except Exception as exc:
            print(f"Failed to generate cache for {photo_path}: {exc}")
            with self.lock:
                self.errors[self._error_key(photo_path)] = str(exc)
        finally:
            with self.lock:
                self.inflight.discard(task_key)

    def _generate(self, photo_path: Path, rel: str) -> None:
        if not photo_path.exists():
            return
        cache_path = self.cache_root / f"{hash_text(rel)}.jpg"
        source_stat = photo_path.stat()

        if (
            cache_path.exists()
            and cache_path.stat().st_mtime >= source_stat.st_mtime
            and cache_path.stat().st_size > 0
        ):
            return

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = cache_path.with_name(f"{cache_path.stem}.tmp.jpg")
        with Image.open(photo_path) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail((self.size, self.size))
            if image.mode not in {"RGB", "L"}:
                image = image.convert("RGB")
            image.save(tmp_path, format="JPEG", quality=self.quality, optimize=True, progressive=True)
        tmp_path.replace(cache_path)

    def delete(self, photo_path: Path) -> None:
        rel = to_relative(self.root, photo_path)
        cache_path = self.cache_root / f"{hash_text(rel)}.jpg"
        try:
            cache_path.unlink()
        except FileNotFoundError:
            pass

    def get_error(self, photo_path: Path) -> str | None:
        with self.lock:
            return self.errors.get(self._error_key(photo_path))

    def _task_key(self, photo_path: Path) -> str:
        stat = photo_path.stat()
        rel = to_relative(self.root, photo_path)
        return f"{rel}:{int(stat.st_mtime)}:{stat.st_size}"

    def _error_key(self, photo_path: Path) -> str:
        return to_relative(self.root, photo_path)


class PhotoFilters:
    def __init__(self, ratings: set[int] | None, date_from: int | None, date_to: int | None) -> None:
        self.ratings = ratings
        self.needs_rating = ratings is not None
        self.date_from = date_from
        self.date_to = date_to

    @classmethod
    def from_request(cls, args: Any) -> "PhotoFilters":
        ratings = parse_rating_filter(args)
        date_from = parse_date_start(args.get("date_from"))
        date_to = parse_date_end(args.get("date_to"))
        return cls(ratings, date_from, date_to)

    def matches_photo(self, photo_rating: int, mtime: int) -> bool:
        if self.ratings is not None and photo_rating not in self.ratings:
            return False
        return self.matches_date(mtime)

    def matches_date(self, mtime: int) -> bool:
        if self.date_from is not None and mtime < self.date_from:
            return False
        if self.date_to is not None and mtime > self.date_to:
            return False
        return True


class BracketFeature:
    def __init__(
        self,
        path: Path,
        rel: str,
        mtime: int,
        width: int,
        height: int,
        brightness: float,
        contrast: float,
        pixels: tuple[float, ...],
        exposure_time: float | None,
        exposure_bias: float | None,
        file_number: int | None,
    ) -> None:
        self.path = path
        self.rel = rel
        self.mtime = mtime
        self.width = width
        self.height = height
        self.brightness = brightness
        self.contrast = contrast
        self.pixels = pixels
        self.exposure_time = exposure_time
        self.exposure_bias = exposure_bias
        self.file_number = file_number


def detect_exposure_brackets(root: Path, folder_path: Path, thumbnails: ImageCacheStore | None = None) -> dict[str, Any]:
    groups: list[list[BracketFeature]] = []
    scanned = 0
    analyzed = 0
    queued = 0
    truncated = False
    for photo_dir in iter_photo_dirs(folder_path):
        photos = [
            child
            for child in photo_dir.iterdir()
            if child.is_file() and child.suffix.lower() in JPG_EXTENSIONS
        ]
        photos.sort(key=photo_sort_key)
        if scanned + len(photos) > BRACKET_SCAN_LIMIT:
            photos = photos[: max(0, BRACKET_SCAN_LIMIT - scanned)]
            truncated = True
        scanned += len(photos)
        features = []
        for photo in photos:
            feature = read_bracket_feature(root, photo, thumbnails)
            if feature is None:
                queued += 1
                continue
            analyzed += 1
            features.append(feature)
        groups.extend(find_bracket_groups_in_features(features))
        if truncated:
            break

    serialized = [serialize_bracket_group(group, group_index + 1) for group_index, group in enumerate(groups)]
    return {
        "groups": serialized,
        "count": len(serialized),
        "scanned": scanned,
        "analyzed": analyzed,
        "queued": queued,
        "truncated": truncated,
    }


def iter_photo_dirs(folder_path: Path) -> list[Path]:
    photo_dirs: list[Path] = []
    for current, dirnames, filenames in os.walk(folder_path):
        dirnames[:] = [
            dirname
            for dirname in dirnames
            if not dirname.startswith(".") and dirname not in {THUMBNAIL_DIR}
        ]
        current_path = Path(current)
        if any(Path(filename).suffix.lower() in JPG_EXTENSIONS for filename in filenames):
            photo_dirs.append(current_path)
    return photo_dirs


def find_bracket_groups_in_features(features: list[BracketFeature]) -> list[list[BracketFeature]]:
    groups: list[list[BracketFeature]] = []
    index = 0

    while index < len(features):
        current = [features[index]]
        index += 1
        while index < len(features) and are_bracket_neighbors(current[-1], features[index]):
            current.append(features[index])
            index += 1
        if is_exposure_bracket_group(current):
            groups.append(current)
    return groups


def read_bracket_feature(root: Path, photo_path: Path, thumbnails: ImageCacheStore | None = None) -> BracketFeature | None:
    try:
        stat = photo_path.stat()
        width = 0
        height = 0
        exposure_time = None
        exposure_bias = None

        feature_source = thumbnails.get_ready(photo_path) if thumbnails is not None else None
        if feature_source is None:
            return None
        with Image.open(feature_source) as image:
            width, height = image.size
            image.draft("L", (64, 64))
            gray = image.convert("L")
        gray.thumbnail((64, 64))
        stat_info = ImageStat.Stat(gray)
        brightness = float(stat_info.mean[0])
        contrast = float(stat_info.stddev[0])
        shape_gray = ImageOps.autocontrast(gray)
        pixels = tuple(value / 255.0 for value in shape_gray.resize((16, 16)).getdata())
    except Exception:
        return None

    return BracketFeature(
        path=photo_path,
        rel=to_relative(root, photo_path),
        mtime=int(stat.st_mtime),
        width=width,
        height=height,
        brightness=brightness,
        contrast=contrast,
        pixels=pixels,
        exposure_time=exposure_time,
        exposure_bias=exposure_bias,
        file_number=trailing_number(photo_path.stem),
    )


def photo_sort_key(path: Path) -> tuple[str, int, str]:
    prefix, number = split_trailing_number(path.stem)
    return (prefix.lower(), number if number is not None else -1, path.name.lower())


def split_trailing_number(value: str) -> tuple[str, int | None]:
    match = re.search(r"(\d+)$", value)
    if not match:
        return (value, None)
    return (value[: match.start()], int(match.group(1)))


def trailing_number(value: str) -> int | None:
    return split_trailing_number(value)[1]


def are_bracket_neighbors(left: BracketFeature, right: BracketFeature) -> bool:
    if not file_numbers_are_close(left, right):
        return False
    if not dimensions_are_close(left, right):
        return False
    similarity = image_similarity(left.pixels, right.pixels)
    if similarity < 0.82:
        return False
    if exposure_step(left, right) < 0.28 and abs(left.brightness - right.brightness) < 9:
        return False
    return True


def file_numbers_are_close(left: BracketFeature, right: BracketFeature) -> bool:
    if left.file_number is None or right.file_number is None:
        return True
    return 1 <= right.file_number - left.file_number <= 2


def dimensions_are_close(left: BracketFeature, right: BracketFeature) -> bool:
    if left.width <= 0 or left.height <= 0 or right.width <= 0 or right.height <= 0:
        return False
    left_ratio = left.width / left.height
    right_ratio = right.width / right.height
    return abs(left_ratio - right_ratio) <= 0.04


def exposure_step(left: BracketFeature, right: BracketFeature) -> float:
    if left.exposure_time and right.exposure_time and left.exposure_time > 0 and right.exposure_time > 0:
        import math

        return abs(math.log2(right.exposure_time / left.exposure_time))
    if left.exposure_bias is not None and right.exposure_bias is not None:
        return abs(right.exposure_bias - left.exposure_bias)
    return 0.0


def is_exposure_bracket_group(group: list[BracketFeature]) -> bool:
    if len(group) < 3:
        return False
    brightness_values = [feature.brightness for feature in group]
    brightness_range = max(brightness_values) - min(brightness_values)
    if brightness_range < 18:
        return False
    similar_pairs = [
        image_similarity(group[index].pixels, group[index + 1].pixels)
        for index in range(len(group) - 1)
    ]
    if min(similar_pairs) < 0.82 or sum(similar_pairs) / len(similar_pairs) < 0.88:
        return False
    exposure_steps = [
        exposure_step(group[index], group[index + 1])
        for index in range(len(group) - 1)
    ]
    has_exif_exposure = any(step >= 0.5 for step in exposure_steps)
    return has_exif_exposure or brightness_range >= 28


def image_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = 0.0
    left_energy = 0.0
    right_energy = 0.0
    for left_value, right_value in zip(left, right):
        left_centered = left_value - left_mean
        right_centered = right_value - right_mean
        numerator += left_centered * right_centered
        left_energy += left_centered * left_centered
        right_energy += right_centered * right_centered
    denominator = (left_energy * right_energy) ** 0.5
    if denominator <= 0:
        return 0.0
    return max(-1.0, min(1.0, numerator / denominator))


def serialize_bracket_group(group: list[BracketFeature], index: int) -> dict[str, Any]:
    brightness_values = [feature.brightness for feature in group]
    similarities = [
        image_similarity(group[item_index].pixels, group[item_index + 1].pixels)
        for item_index in range(len(group) - 1)
    ]
    exposure_values = [feature.exposure_time for feature in group if feature.exposure_time]
    return {
        "id": index,
        "size": len(group),
        "brightnessRange": round(max(brightness_values) - min(brightness_values), 1),
        "averageSimilarity": round(sum(similarities) / len(similarities), 3) if similarities else 1,
        "exposureRangeEv": round(exposure_range_ev(exposure_values), 2) if len(exposure_values) >= 2 else None,
        "photos": [
            {
                "name": feature.path.name,
                "path": feature.rel,
                "mtime": feature.mtime,
                "brightness": round(feature.brightness, 1),
                "exposureTime": feature.exposure_time,
                "exposureBias": feature.exposure_bias,
                "thumbUrl": thumb_url(feature.rel),
            }
            for feature in group
        ],
    }


def exposure_range_ev(values: list[float]) -> float:
    import math

    minimum = min(value for value in values if value > 0)
    maximum = max(value for value in values if value > 0)
    return abs(math.log2(maximum / minimum))


def rational_to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        pass
    try:
        numerator, denominator = value
        denominator = float(denominator)
        if denominator == 0:
            return None
        return float(numerator) / denominator
    except (TypeError, ValueError, ZeroDivisionError):
        return None


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


def thumb_url(photo_path: str, mode: str = DEFAULT_THUMBNAIL_MODE) -> str:
    safe_mode = get_thumbnail_mode(mode)
    return f"/api/thumb/{quote_path(normalize_rel_path(photo_path))}?mode={safe_mode}"


def preview_url(photo_path: str) -> str:
    return f"/api/preview/{quote_path(normalize_rel_path(photo_path))}"


def image_url(photo_path: str) -> str:
    return f"/api/image/{quote_path(normalize_rel_path(photo_path))}"


def prewarm_folder_assets(
    folder_path: Path,
    thumbnails: ImageCacheStore,
    previews: ImageCacheStore,
    limit: int,
) -> None:
    count = 0
    for child in sorted(folder_path.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_file() or child.suffix.lower() not in JPG_EXTENSIONS:
            continue
        thumbnails.ensure(child)
        previews.ensure(child)
        count += 1
        if count >= limit:
            break


def quote_path(path: str) -> str:
    from urllib.parse import quote

    return "/".join(quote(part) for part in path.split("/"))


def root_cache_key(root: Path) -> str:
    return hash_text(str(root).lower())


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_thumbnail_modes(base_size: int, base_quality: int) -> dict[str, dict[str, int]]:
    modes = {mode: spec.copy() for mode, spec in THUMBNAIL_MODES.items()}
    modes[DEFAULT_THUMBNAIL_MODE] = {"size": base_size, "quality": base_quality}
    return modes


def get_thumbnail_mode(value: str | None) -> str:
    if not value:
        return DEFAULT_THUMBNAIL_MODE
    if value not in THUMBNAIL_MODES:
        abort(400, "thumbnail mode must be small, medium, or large.")
    return value


def parse_optional_int(value: str | None, minimum: int, maximum: int) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except ValueError:
        abort(400, f"Expected integer from {minimum} to {maximum}.")
    if parsed < minimum or parsed > maximum:
        abort(400, f"Expected integer from {minimum} to {maximum}.")
    return parsed


def parse_rating_filter(args: Any) -> set[int] | None:
    raw_values = args.getlist("rating") if hasattr(args, "getlist") else [args.get("rating")]
    ratings: set[int] = set()
    for raw in raw_values:
        if raw is None or raw == "":
            continue
        for item in str(raw).split(","):
            if item == "":
                continue
            rating = parse_optional_int(item, 0, 5)
            if rating is not None:
                ratings.add(rating)
    if not ratings or ratings == set(range(0, 6)):
        return None
    return ratings


def parse_date_start(value: str | None) -> int | None:
    if not value:
        return None
    from datetime import datetime

    try:
        return int(datetime.fromisoformat(value).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    except ValueError:
        abort(400, "date_from must use YYYY-MM-DD format.")


def parse_date_end(value: str | None) -> int | None:
    if not value:
        return None
    from datetime import datetime

    try:
        return int(datetime.fromisoformat(value).replace(hour=23, minute=59, second=59, microsecond=999999).timestamp())
    except ValueError:
        abort(400, "date_to must use YYYY-MM-DD format.")


def read_embedded_rating(photo_path: Path) -> int:
    rating = read_xmp_rating(photo_path)
    if rating:
        return rating
    return read_exif_rating(photo_path)


def read_exif_rating(photo_path: Path) -> int:
    try:
        with Image.open(photo_path) as image:
            exif = image.getexif()
    except Exception:
        return 0

    rating = normalize_rating_value(exif.get(18246))
    if rating:
        return rating

    percent = exif.get(18249)
    try:
        percent_int = int(percent)
    except (TypeError, ValueError):
        return 0
    return normalize_rating_percent(percent_int)


def read_xmp_rating(photo_path: Path) -> int:
    rating = read_xmp_head_rating(photo_path)
    if rating:
        return rating

    try:
        file_size = photo_path.stat().st_size
    except OSError:
        file_size = 0

    try:
        if file_size > 128 * 1024:
            with photo_path.open("rb") as file:
                file.seek(max(0, file_size - 128 * 1024))
                tail = file.read()
            rating = parse_xmp_rating(tail)
            if rating:
                return rating
    except OSError:
        pass

    sidecar = photo_path.with_suffix(".xmp")
    if sidecar.exists():
        try:
            return parse_xmp_rating(sidecar.read_bytes())
        except OSError:
            return 0
    return 0


def read_xmp_head_rating(photo_path: Path) -> int:
    try:
        with photo_path.open("rb") as file:
            head = file.read(128 * 1024)
    except OSError:
        return 0
    return parse_xmp_rating(head)


def parse_xmp_rating(raw: bytes) -> int:
    if not raw:
        return 0
    text = raw.decode("utf-8", errors="ignore")
    patterns = (
        r"\bxmp:Rating\s*=\s*['\"]\s*(-?\d+)\s*['\"]",
        r"<\s*xmp:Rating\s*>\s*(-?\d+)\s*<\s*/\s*xmp:Rating\s*>",
        r"\brating\s*=\s*['\"]\s*(-?\d+)\s*['\"]",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return normalize_rating_value(match.group(1))
    return 0


def normalize_rating_value(value: Any) -> int:
    try:
        rating = int(value)
    except (TypeError, ValueError):
        return 0
    if rating < 1:
        return 0
    return min(rating, 5)


def normalize_rating_percent(value: int) -> int:
    if value <= 0:
        return 0
    if value <= 1:
        return 1
    if value <= 25:
        return 2
    if value <= 50:
        return 3
    if value <= 75:
        return 4
    return 5


def write_embedded_rating(photo_path: Path, rating: int) -> None:
    exif_dict = load_exif_dict(photo_path)
    zeroth = exif_dict.setdefault("0th", {})
    zeroth[18246] = int(rating)
    zeroth[18249] = rating_to_percent(rating)
    exif_bytes = piexif.dump(exif_dict)
    piexif.insert(exif_bytes, str(photo_path))


def load_exif_dict(photo_path: Path) -> dict[str, Any]:
    try:
        exif_dict = piexif.load(str(photo_path))
    except Exception:
        exif_dict = {}
    return {
        "0th": dict(exif_dict.get("0th", {})),
        "Exif": dict(exif_dict.get("Exif", {})),
        "GPS": dict(exif_dict.get("GPS", {})),
        "Interop": dict(exif_dict.get("Interop", {})),
        "1st": dict(exif_dict.get("1st", {})),
        "thumbnail": exif_dict.get("thumbnail"),
    }


def rating_to_percent(rating: int) -> int:
    if rating <= 0:
        return 0
    if rating >= 5:
        return 99
    return rating * 20


def create_default_config(config_path: Path) -> None:
    config_path.write_text(
        json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_config(config_path: Path) -> dict[str, Any] | None:
    if not config_path.exists():
        create_default_config(config_path)
        print(f"Config file was not found. Created default config: {config_path}")
        print("Edit photo_folder in the config file, then start the app again.")
        return None

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON config: {config_path} ({exc})") from exc

    if not isinstance(config, dict):
        raise ValueError("Config root must be a JSON object.")
    return config


def get_config_path(value: str | None) -> Path:
    if not value:
        return DEFAULT_CONFIG_FILE
    return Path(value).expanduser().resolve()


def get_photo_folder(config: dict[str, Any]) -> Path:
    value = config.get("photo_folder")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Config field photo_folder must be a non-empty string.")
    return Path(value).expanduser()


def get_host(config: dict[str, Any]) -> str:
    value = config.get("host", DEFAULT_CONFIG["host"])
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Config field host must be a non-empty string.")
    return value


def get_port(config: dict[str, Any]) -> int:
    value = config.get("port", DEFAULT_CONFIG["port"])
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Config field port must be an integer.") from exc
    if port < 1 or port > 65535:
        raise ValueError("Config field port must be between 1 and 65535.")
    return port


def get_thumbnail_size(config: dict[str, Any]) -> int:
    value = config.get("thumbnail_size", DEFAULT_THUMBNAIL_SIZE)
    try:
        size = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Config field thumbnail_size must be an integer.") from exc
    if size < 160 or size > 1200:
        raise ValueError("Config field thumbnail_size must be between 160 and 1200.")
    return size


def get_thumbnail_quality(config: dict[str, Any]) -> int:
    value = config.get("thumbnail_quality", DEFAULT_THUMBNAIL_QUALITY)
    try:
        quality = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Config field thumbnail_quality must be an integer.") from exc
    if quality < 40 or quality > 92:
        raise ValueError("Config field thumbnail_quality must be between 40 and 92.")
    return quality


def get_preview_size(config: dict[str, Any]) -> int:
    value = config.get("preview_size", DEFAULT_PREVIEW_SIZE)
    try:
        size = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Config field preview_size must be an integer.") from exc
    if size < 800 or size > 4000:
        raise ValueError("Config field preview_size must be between 800 and 4000.")
    return size


def get_preview_quality(config: dict[str, Any]) -> int:
    value = config.get("preview_quality", DEFAULT_PREVIEW_QUALITY)
    try:
        quality = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Config field preview_quality must be an integer.") from exc
    if quality < 50 or quality > 95:
        raise ValueError("Config field preview_quality must be between 50 and 95.")
    return quality


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Share a local JPG folder on your LAN.")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_FILE),
        help="JSON config file path. Default: config.json next to app.py",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    config_path = get_config_path(args.config)
    config = load_config(config_path)
    if config is None:
        raise SystemExit(0)

    folder = get_photo_folder(config)
    host = get_host(config)
    port = get_port(config)
    thumbnail_size = get_thumbnail_size(config)
    thumbnail_quality = get_thumbnail_quality(config)
    preview_size = get_preview_size(config)
    preview_quality = get_preview_quality(config)
    app = create_app(
        folder,
        thumbnail_size=thumbnail_size,
        thumbnail_quality=thumbnail_quality,
        preview_size=preview_size,
        preview_quality=preview_quality,
    )
    print(f"Config: {config_path}")
    print(f"Sharing: {folder.resolve()}")
    print(f"Open on this computer: http://127.0.0.1:{port}")
    print("Open on LAN devices: http://<this-computer-LAN-IP>:%s" % port)
    app.run(host=host, port=port, debug=False)
