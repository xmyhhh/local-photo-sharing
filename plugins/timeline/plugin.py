from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass
from datetime import datetime
from os import scandir
from pathlib import Path
from typing import Any

import piexif
from flask import Flask, abort, jsonify, request

from core.photo_share.constants import CACHE_DIR, MEDIA_EXTENSIONS, PHOTO_EXTENSIONS, RATINGS_FILE, THUMBNAIL_DIR, VIDEO_EXTENSIONS, CPU_COUNT
from core.photo_share.context import AppServices
from core.photo_share.live_photos import find_case_insensitive_sibling, find_live_video
from core.photo_share.paths import image_url, join_rooted_path, root_cache_key, thumb_url, to_relative

PLUGIN_NAME = "timeline"
SCAN_INTERVAL_SECONDS = 120
MAX_TIMELINE_ITEMS = 300_000
MAX_PAGE_SIZE = 600
INDEX_CACHE_VERSION = 1
INDEX_CACHE_FILE = "timeline_index_v1.json"
INDEX_WORKERS = min(16, max(2, CPU_COUNT))
INDEX_INFLIGHT_LIMIT = INDEX_WORKERS * 8
IGNORED_DIR_NAMES = {
    ".git",
    ".photo_share_cache",
    ".photo_share_thumbs",
    ".photo_share_trash",
    "__pycache__",
}


PLUGIN = {
    "title": "时间线",
    "description": "按拍摄日期把所有图库照片排成时间线，并支持只看精选照片。",
    "static_dir": "static",
    "scripts": ["timeline.js"],
    "styles": ["timeline.css"],
    "components": [
        {
            "id": "timeline.open",
            "title": "时间线",
            "description": "以时间线方式浏览所有图库照片和视频。",
            "capabilities": [
                {"type": "background_service", "operations": ["index", "refresh", "release"]},
                {"type": "function", "operations": ["browse", "featured"]},
            ],
            "triggers": [
                {"type": "topbar_button", "label": "时间线", "icon": "◷", "action": "timeline.open"},
            ],
            "surfaces": [
                {"type": "dialog", "id": "timelineDialog"},
            ],
        }
    ],
}


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    root_id: str
    rel: str
    name: str
    type: str
    size: int
    mtime: int
    taken_ts: int
    rating: int
    browser_renderable: bool
    is_live: bool
    live_video_path: str | None


class TimelineIndex:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._services: AppServices | None = None
        self._entries: list[TimelineEntry] = []
        self._indexed_at = 0.0
        self._indexing = False
        self._error = ""
        self._generation = 0
        self._scanned_count = 0

    def start(self, services: AppServices) -> None:
        with self._lock:
            self._services = services
            self._stop.clear()
            self._load_cache(services)
            if self._thread and self._thread.is_alive():
                self.request_refresh()
                return
            self._thread = threading.Thread(target=self._run, name="timeline-index", daemon=True)
            self._thread.start()
        self.request_refresh()

    def stop(self) -> None:
        with self._lock:
            self._stop.set()
            self._wake.set()
            thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2)
        with self._lock:
            self._thread = None
            self._services = None
            self._entries = []
            self._indexed_at = 0.0
            self._indexing = False
            self._error = ""
            self._generation = 0
            self._scanned_count = 0

    def request_refresh(self) -> None:
        self._wake.set()

    def status(self) -> dict[str, Any]:
        with self._lock:
            featured = sum(1 for entry in self._entries if entry.rating > 0)
            estimated_total = estimate_total_media(self._services)
            return {
                "enabled": self._services is not None,
                "indexing": self._indexing,
                "count": len(self._entries),
                "featuredCount": featured,
                "indexedAt": int(self._indexed_at),
                "error": self._error,
                "generation": self._generation,
                "scanned": self._scanned_count,
                "estimatedTotal": estimated_total,
                "progress": min(1.0, self._scanned_count / estimated_total) if estimated_total else None,
            }

    def page(self, featured: bool, cursor: int, limit: int) -> dict[str, Any]:
        limit = max(1, min(limit, MAX_PAGE_SIZE))
        cursor = max(0, cursor)
        with self._lock:
            source = [entry for entry in self._entries if not featured or entry.rating > 0]
            items = source[cursor:cursor + limit]
            next_cursor = cursor + len(items) if cursor + len(items) < len(source) else None
            return {
                "items": [serialize_entry(entry) for entry in items],
                "nextCursor": next_cursor,
                "status": self.status(),
            }

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(SCAN_INTERVAL_SECONDS)
            self._wake.clear()
            if self._stop.is_set():
                break
            services = self._services
            if services is not None:
                self._scan(services)

    def _scan(self, services: AppServices) -> None:
        with self._lock:
            self._indexing = True
            self._error = ""
            self._scanned_count = 0
        entries: list[TimelineEntry] = []
        try:
            for root_id, root_services in services.root_services.items():
                if self._stop.is_set() or len(entries) >= MAX_TIMELINE_ITEMS:
                    break
                budget = MAX_TIMELINE_ITEMS - len(entries)
                for entry in iter_root_media(root_id, root_services, self._stop, budget):
                    entries.append(entry)
                    if should_publish_partial(len(entries)):
                        self._publish_partial(entries)
            entries.sort(key=lambda entry: (-entry.taken_ts, entry.root_id, entry.rel.lower()))
            with self._lock:
                self._entries = entries
                self._indexed_at = time.time()
                self._generation += 1
                self._scanned_count = len(entries)
            self._save_cache(services, entries)
        except Exception as exc:  # noqa: BLE001 - background plugin must not crash Flask.
            with self._lock:
                self._error = str(exc)
        finally:
            with self._lock:
                self._indexing = False

    def _publish_partial(self, entries: list[TimelineEntry]) -> None:
        partial = sorted(entries, key=lambda entry: (-entry.taken_ts, entry.root_id, entry.rel.lower()))
        with self._lock:
            self._entries = partial
            self._scanned_count = len(entries)

    def _load_cache(self, services: AppServices) -> None:
        entries: list[TimelineEntry] = []
        newest_cache = 0.0
        for root_id, root_services in services.root_services.items():
            cache_path = timeline_cache_path(root_services.root)
            try:
                raw = json.loads(cache_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if raw.get("version") != INDEX_CACHE_VERSION:
                continue
            for item in raw.get("entries", []):
                entry = timeline_entry_from_cache(root_id, item)
                if entry is not None:
                    entries.append(entry)
                    if len(entries) >= MAX_TIMELINE_ITEMS:
                        break
            try:
                newest_cache = max(newest_cache, cache_path.stat().st_mtime)
            except OSError:
                pass
            if len(entries) >= MAX_TIMELINE_ITEMS:
                break
        if not entries:
            return
        entries.sort(key=lambda entry: (-entry.taken_ts, entry.root_id, entry.rel.lower()))
        with self._lock:
            self._entries = entries
            self._indexed_at = newest_cache or time.time()
            self._generation += 1
            self._scanned_count = len(entries)

    def _save_cache(self, services: AppServices, entries: list[TimelineEntry]) -> None:
        by_root: dict[str, list[TimelineEntry]] = {}
        for entry in entries:
            by_root.setdefault(entry.root_id, []).append(entry)
        for root_id, root_services in services.root_services.items():
            cache_path = timeline_cache_path(root_services.root)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": INDEX_CACHE_VERSION,
                "createdAt": int(time.time()),
                "entries": [
                    cache_entry(entry)
                    for entry in by_root.get(root_id, [])
                ],
            }
            tmp_path = cache_path.with_suffix(".tmp")
            try:
                tmp_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
                tmp_path.replace(cache_path)
            except OSError:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass


INDEX = TimelineIndex()


def register(app: Flask, services: AppServices) -> None:
    @app.get("/api/timeline/status")
    def timeline_status():
        return jsonify(INDEX.status())

    @app.post("/api/timeline/refresh")
    def timeline_refresh():
        if PLUGIN_NAME not in services.enabled_plugins:
            abort(404)
        INDEX.request_refresh()
        return jsonify(INDEX.status())

    @app.get("/api/timeline/items")
    def timeline_items():
        if PLUGIN_NAME not in services.enabled_plugins:
            abort(404)
        featured = request.args.get("featured") in {"1", "true", "yes"}
        cursor = parse_int(request.args.get("cursor"), 0)
        limit = parse_int(request.args.get("limit"), 160)
        return jsonify(INDEX.page(featured, cursor, limit))


def on_enable(services: AppServices) -> None:
    INDEX.start(services)


def on_disable(services: AppServices) -> None:
    INDEX.stop()


def parse_int(value: str | None, fallback: int) -> int:
    try:
        return int(value or fallback)
    except (TypeError, ValueError):
        return fallback


def should_publish_partial(count: int) -> bool:
    if count <= 60:
        return count % 10 == 0
    return count % 100 == 0


def estimate_total_media(services: AppServices | None) -> int:
    if services is None:
        return 0
    total = 0
    for root_services in services.root_services.values():
        count = root_services.folder_counts.get(root_services.root)
        if count is None:
            return 0
        total += count
    return total


def timeline_cache_path(root: Path) -> Path:
    return CACHE_DIR / root_cache_key(root) / INDEX_CACHE_FILE


def cache_entry(entry: TimelineEntry) -> dict[str, Any]:
    data = asdict(entry)
    data.pop("root_id", None)
    return data


def timeline_entry_from_cache(root_id: str, data: Any) -> TimelineEntry | None:
    if not isinstance(data, dict):
        return None
    try:
        rel = str(data["rel"])
        name = str(data.get("name") or Path(rel).name)
        entry_type = str(data.get("type") or "photo")
        if entry_type not in {"photo", "video"}:
            return None
        return TimelineEntry(
            root_id=root_id,
            rel=rel,
            name=name,
            type=entry_type,
            size=int(data.get("size") or 0),
            mtime=int(data.get("mtime") or 0),
            taken_ts=int(data.get("taken_ts") or data.get("takenAt") or data.get("mtime") or 0),
            rating=max(0, min(5, int(data.get("rating") or 0))),
            browser_renderable=bool(data.get("browser_renderable", data.get("browserRenderable", False))),
            is_live=bool(data.get("is_live", data.get("isLive", False))),
            live_video_path=data.get("live_video_path") or data.get("liveVideoPath"),
        )
    except (TypeError, ValueError, KeyError):
        return None


def iter_root_media(root_id: str, root_services, stop: threading.Event, budget: int):
    with ThreadPoolExecutor(max_workers=INDEX_WORKERS, thread_name_prefix=f"timeline-index-{root_id}") as executor:
        yield from iter_root_media_parallel(root_id, root_services, stop, budget, executor)


def iter_root_media_parallel(root_id: str, root_services, stop: threading.Event, budget: int, executor: ThreadPoolExecutor):
    root = root_services.root
    stack = [root]
    emitted = 0
    futures: set[Future[TimelineEntry | None]] = set()
    while stack and not stop.is_set() and emitted < budget:
        folder = stack.pop()
        try:
            children = scandir(folder)
        except OSError:
            continue
        sibling_map: dict[tuple[str, str], Path] = {}
        pending_files: list[Path] = []
        with children:
            for child in children:
                if stop.is_set():
                    return
                try:
                    path = Path(child.path)
                    if should_skip(path):
                        continue
                    if child.is_dir():
                        stack.append(path)
                    elif child.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS:
                        sibling_map[(path.stem.lower(), path.suffix.lower())] = path
                        pending_files.append(path)
                except OSError:
                    continue
        for path in pending_files:
            if stop.is_set() or emitted + len(futures) >= budget:
                break
            if path.suffix.lower() in VIDEO_EXTENSIONS and has_live_photo_still(path, sibling_map):
                continue
            futures.add(executor.submit(build_timeline_entry, root_id, root_services, path, sibling_map))
            if len(futures) >= INDEX_INFLIGHT_LIMIT:
                for entry in drain_completed_entries(futures, stop, wait_for_one=True):
                    yield entry
                    emitted += 1
                    if emitted >= budget:
                        return
        for entry in drain_completed_entries(futures, stop, wait_for_one=False):
            yield entry
            emitted += 1
            if emitted >= budget:
                return
    for entry in drain_completed_entries(futures, stop, wait_for_all=True):
        yield entry


def drain_completed_entries(
    futures: set[Future[TimelineEntry | None]],
    stop: threading.Event,
    wait_for_one: bool = False,
    wait_for_all: bool = False,
):
    while futures and not stop.is_set():
        if wait_for_all:
            done, _ = wait(futures, timeout=0.2, return_when=FIRST_COMPLETED)
        elif wait_for_one:
            done, _ = wait(futures, timeout=0.2, return_when=FIRST_COMPLETED)
        else:
            done = {future for future in futures if future.done()}
        if not done:
            return
        futures.difference_update(done)
        for future in done:
            try:
                entry = future.result()
            except Exception:
                entry = None
            if entry is not None:
                yield entry
        if not wait_for_all:
            return


def should_skip(path: Path) -> bool:
    return path.name in IGNORED_DIR_NAMES or path.name == RATINGS_FILE or path.name == THUMBNAIL_DIR


def has_live_photo_still(video_path: Path, sibling_map: dict[tuple[str, str], Path]) -> bool:
    stem = video_path.stem.lower()
    return any((stem, suffix) in sibling_map for suffix in PHOTO_EXTENSIONS)


def build_timeline_entry(root_id: str, root_services, path: Path, sibling_map: dict[tuple[str, str], Path]) -> TimelineEntry | None:
    suffix = path.suffix.lower()
    if suffix not in MEDIA_EXTENSIONS:
        return None
    try:
        stat = path.stat()
    except OSError:
        return None
    rel = to_relative(root_services.root, path)
    is_photo = suffix in PHOTO_EXTENSIONS
    rating = photo_rating(rel, path, root_services) if is_photo else 0
    live_video = find_live_video_from_map(path, sibling_map) if is_photo else None
    return TimelineEntry(
        root_id=root_id,
        rel=rel,
        name=path.name,
        type="photo" if is_photo else "video",
        size=stat.st_size,
        mtime=int(stat.st_mtime),
        taken_ts=photo_taken_timestamp(path, stat) if is_photo else int(stat.st_mtime),
        rating=rating,
        browser_renderable=suffix in {".jpg", ".jpeg"},
        is_live=live_video is not None,
        live_video_path=join_rooted_path(root_id, to_relative(root_services.root, live_video)) if live_video else None,
    )


def photo_rating(rel: str, path: Path, root_services) -> int:
    override = root_services.ratings.get_override(rel)
    if override is not None:
        return override
    indexed = root_services.rating_index.get(rel)
    if indexed is not None:
        return indexed
    try:
        if root_services.metadata.is_ready(path):
            return root_services.metadata.get_rating_ready(path)
        return root_services.rating_index.ensure_photo_quick(path)
    except Exception:
        return root_services.metadata.get_rating_ready(path)


def find_live_video_from_map(photo_path: Path, sibling_map: dict[tuple[str, str], Path]) -> Path | None:
    stem = photo_path.stem.lower()
    for suffix in VIDEO_EXTENSIONS:
        video = sibling_map.get((stem, suffix))
        if video is not None:
            return video
    return find_case_insensitive_sibling(photo_path, VIDEO_EXTENSIONS)


def photo_taken_timestamp(path: Path, stat: os.stat_result) -> int:
    taken = read_exif_taken_at(path)
    if taken is None:
        return int(stat.st_mtime)
    return int(taken.timestamp())


def read_exif_taken_at(path: Path) -> datetime | None:
    try:
        exif = piexif.load(str(path))
    except Exception:
        return None
    exif_ifd = exif.get("Exif", {})
    zeroth = exif.get("0th", {})
    raw = (
        decode_exif_text(exif_ifd.get(piexif.ExifIFD.DateTimeOriginal))
        or decode_exif_text(exif_ifd.get(piexif.ExifIFD.DateTimeDigitized))
        or decode_exif_text(zeroth.get(piexif.ImageIFD.DateTime))
    )
    if not raw:
        return None
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def decode_exif_text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore").strip("\x00 ")
    return str(value).strip()


def serialize_entry(entry: TimelineEntry) -> dict[str, Any]:
    path = join_rooted_path(entry.root_id, entry.rel)
    result = {
        "type": entry.type,
        "name": entry.name,
        "path": path,
        "root": entry.root_id,
        "rel": entry.rel,
        "size": entry.size,
        "mtime": entry.mtime,
        "takenAt": entry.taken_ts,
        "rating": entry.rating,
        "ratingPending": False,
        "browserRenderable": entry.browser_renderable,
        "isLive": entry.is_live,
        "liveVideoPath": entry.live_video_path,
        "originalUrl": image_url(path),
    }
    if entry.type == "photo":
        result["thumbUrl"] = thumb_url(path, "small")
    return result
