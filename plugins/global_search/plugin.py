from __future__ import annotations

import json
import threading
import time
import unicodedata
from dataclasses import asdict, dataclass, replace
from os import scandir
from pathlib import Path
from typing import Any

from flask import Flask, abort, jsonify, request

from core.photo_share.constants import CACHE_DIR, MEDIA_EXTENSIONS, PHOTO_EXTENSIONS, RATINGS_FILE, THUMBNAIL_DIR
from core.photo_share.context import AppServices
from core.photo_share.paths import join_rooted_path, root_cache_key, thumb_url, to_relative

PLUGIN_NAME = "global_search"
MAX_QUERY_RESULTS = 200
MAX_INDEX_ITEMS = 300_000
INDEX_CACHE_VERSION = 1
INDEX_CACHE_FILE = "global_search_index_v1.json"
REFRESH_AFTER_SECONDS = 30 * 60
IGNORED_DIR_NAMES = {
    ".git",
    ".photo_share_cache",
    ".photo_share_thumbs",
    ".photo_share_trash",
    "__pycache__",
}


PLUGIN = {
    "title": "全局搜索",
    "description": "为所有图库目录建立轻量文件索引，支持跨目录搜索文件夹、图片和视频。",
    "static_dir": "static",
    "scripts": ["global_search.js"],
    "styles": ["global_search.css"],
    "components": [
        {
            "id": "global_search.open",
            "title": "全局搜索",
            "description": "搜索所有已配置图库目录中的文件夹、图片和视频。",
            "capabilities": [
                {"type": "background_service", "operations": ["index", "refresh", "release"]},
                {"type": "function", "operations": ["search"]},
            ],
            "triggers": [
                {"type": "topbar_button", "label": "搜索", "action": "global_search.open"},
            ],
            "surfaces": [
                {"type": "dialog", "id": "globalSearchDialog"},
            ],
        }
    ],
}


@dataclass(frozen=True, slots=True)
class SearchEntry:
    root_id: str
    rel: str
    name: str
    type: str
    size: int
    mtime: int
    preview_rel: str = ""
    search_text: str = ""
    name_key: str = ""


class GlobalSearchIndex:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._services: AppServices | None = None
        self._entries: list[SearchEntry] = []
        self._indexed_at = 0.0
        self._indexing = False
        self._error = ""
        self._generation = 0
        self._wake = threading.Event()

    def start(self, services: AppServices) -> None:
        with self._lock:
            self._services = services
            self._stop.clear()
            self._load_cache(services)
            if self._thread and self._thread.is_alive():
                self._wake.set()
                return
            self._thread = threading.Thread(target=self._run, name="global-search-index", daemon=True)
            self._thread.start()
            self._wake.set()

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

    def request_refresh(self) -> None:
        self._wake.set()

    def request_refresh_if_empty(self) -> None:
        with self._lock:
            should_refresh = self._services is not None and not self._entries and not self._indexing
        if should_refresh:
            self.request_refresh()

    def request_refresh_if_stale(self) -> None:
        with self._lock:
            should_refresh = (
                self._services is not None
                and not self._indexing
                and (not self._entries or time.time() - self._indexed_at > REFRESH_AFTER_SECONDS)
            )
        if should_refresh:
            self.request_refresh()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self._services is not None,
                "indexing": self._indexing,
                "count": len(self._entries),
                "indexedAt": int(self._indexed_at),
                "error": self._error,
                "generation": self._generation,
            }

    def search(self, query: str, limit: int = 80) -> list[dict[str, Any]]:
        tokens = normalize_query(query)
        if not tokens:
            return []
        limit = max(1, min(limit, MAX_QUERY_RESULTS))
        scored: list[tuple[int, SearchEntry]] = []
        with self._lock:
            for entry in self._entries:
                score = match_score(entry, tokens)
                if score > 0:
                    scored.append((score, entry))
        scored.sort(key=lambda item: (-item[0], item[1].type != "folder", item[1].rel.lower()))
        return [serialize_entry(entry) for _, entry in scored[:limit]]

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait()
            self._wake.clear()
            if self._stop.is_set():
                break
            services = self._services
            if services is None:
                continue
            self._scan(services)

    def _scan(self, services: AppServices) -> None:
        with self._lock:
            self._indexing = True
            self._error = ""
        entries: list[SearchEntry] = []
        try:
            for root_id, root in services.roots.items():
                if self._stop.is_set() or len(entries) >= MAX_INDEX_ITEMS:
                    break
                entries.append(build_root_entry(root_id, root))
                if len(entries) >= MAX_INDEX_ITEMS:
                    break
                entries.extend(iter_root_entries(root_id, root, self._stop, MAX_INDEX_ITEMS - len(entries)))
            entries = attach_folder_previews(entries)
            with self._lock:
                self._entries = entries
                self._indexed_at = time.time()
                self._generation += 1
            self._save_cache(services, entries)
        except Exception as exc:  # noqa: BLE001 - plugin background task must not crash Flask.
            with self._lock:
                self._error = str(exc)
        finally:
            with self._lock:
                self._indexing = False

    def _load_cache(self, services: AppServices) -> None:
        entries: list[SearchEntry] = []
        newest_cache = 0.0
        for root_id, root in services.roots.items():
            cache_path = search_cache_path(root)
            try:
                raw = json.loads(cache_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if raw.get("version") != INDEX_CACHE_VERSION:
                continue
            for item in raw.get("entries", []):
                entry = search_entry_from_cache(root_id, item)
                if entry is None:
                    continue
                entries.append(entry)
                if len(entries) >= MAX_INDEX_ITEMS:
                    break
            try:
                newest_cache = max(newest_cache, cache_path.stat().st_mtime)
            except OSError:
                pass
            if len(entries) >= MAX_INDEX_ITEMS:
                break
        if not entries:
            return
        with self._lock:
            self._entries = entries
            self._indexed_at = newest_cache or time.time()
            self._generation += 1

    def _save_cache(self, services: AppServices, entries: list[SearchEntry]) -> None:
        by_root: dict[str, list[SearchEntry]] = {}
        for entry in entries:
            by_root.setdefault(entry.root_id, []).append(entry)
        for root_id, root in services.roots.items():
            cache_path = search_cache_path(root)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": INDEX_CACHE_VERSION,
                "createdAt": int(time.time()),
                "entries": [cache_entry(entry) for entry in by_root.get(root_id, [])],
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


INDEX = GlobalSearchIndex()


def register(app: Flask, services: AppServices) -> None:
    @app.get("/api/global-search/status")
    def global_search_status():
        if request.args.get("prepare") in {"1", "true", "yes"}:
            INDEX.request_refresh_if_stale()
        return jsonify(INDEX.status())

    @app.post("/api/global-search/refresh")
    def global_search_refresh():
        INDEX.request_refresh()
        return jsonify(INDEX.status())

    @app.get("/api/global-search/search")
    def global_search_query():
        if PLUGIN_NAME not in services.enabled_plugins:
            abort(404)
        query = request.args.get("q", "")
        limit = parse_limit(request.args.get("limit"))
        INDEX.request_refresh_if_empty()
        return jsonify({
            "query": query,
            "results": INDEX.search(query, limit),
            "status": INDEX.status(),
        })


def on_enable(services: AppServices) -> None:
    INDEX.start(services)


def on_disable(services: AppServices) -> None:
    INDEX.stop()


def get_backend_tasks(services: AppServices) -> list[dict[str, Any]]:
    status = INDEX.status()
    if not status.get("indexing") and not status.get("error"):
        return []
    return [{
        "id": "global_search_index",
        "title": "全局搜索索引",
        "detail": f"已索引 {status.get('count', 0)} 项",
        "state": "indexing" if status.get("indexing") else "error",
        "progress": None,
        "progressMode": "activity",
        "completed": status.get("count"),
        "total": None,
        "error": status.get("error", ""),
        "meta": {
            "generation": status.get("generation", 0),
        },
    }]


def parse_limit(value: str | None) -> int:
    try:
        return int(value or "80")
    except ValueError:
        return 80


def iter_root_entries(root_id: str, root: Path, stop: threading.Event, budget: int):
    if budget <= 0:
        return
    stack = [root]
    emitted = 0
    while stack and not stop.is_set() and emitted < budget:
        folder = stack.pop()
        try:
            children = scandir(folder)
        except OSError:
            continue
        with children:
            for child in children:
                if stop.is_set() or emitted >= budget:
                    return
                try:
                    child_path = Path(child.path)
                    if should_skip(child_path):
                        continue
                    if child.is_dir():
                        stack.append(child_path)
                        yield build_entry(root_id, root, child_path, "folder")
                        emitted += 1
                    elif child.is_file() and child_path.suffix.lower() in MEDIA_EXTENSIONS:
                        yield build_entry(root_id, root, child_path, "media")
                        emitted += 1
                except OSError:
                    continue


def should_skip(path: Path) -> bool:
    return path.name in IGNORED_DIR_NAMES or path.name == RATINGS_FILE or path.name == THUMBNAIL_DIR


def build_entry(root_id: str, root: Path, path: Path, item_type: str) -> SearchEntry:
    stat = path.stat()
    rel = to_relative(root, path)
    return with_search_keys(SearchEntry(
        root_id=root_id,
        rel=rel,
        name=path.name,
        type=item_type,
        size=stat.st_size if item_type != "folder" else 0,
        mtime=int(stat.st_mtime),
        preview_rel=rel if item_type == "media" and path.suffix.lower() in PHOTO_EXTENSIONS else "",
    ))


def build_root_entry(root_id: str, root: Path) -> SearchEntry:
    try:
        stat = root.stat()
        mtime = int(stat.st_mtime)
    except OSError:
        mtime = 0
    return with_search_keys(SearchEntry(
        root_id=root_id,
        rel="",
        name=root.name or root_id,
        type="folder",
        size=0,
        mtime=mtime,
    ))


def attach_folder_previews(entries: list[SearchEntry]) -> list[SearchEntry]:
    previews: dict[tuple[str, str], str] = {}
    for entry in entries:
        if entry.type != "media" or not entry.preview_rel:
            continue
        folder = parent_rel(entry.rel)
        while True:
            previews.setdefault((entry.root_id, folder), entry.preview_rel)
            if not folder:
                break
            folder = parent_rel(folder)
    return [
        replace(entry, preview_rel=previews.get((entry.root_id, entry.rel), ""))
        if entry.type == "folder" else entry
        for entry in entries
    ]


def parent_rel(value: str) -> str:
    parent = Path(value).parent.as_posix()
    return "" if parent == "." else parent


def normalize_query(query: str) -> list[str]:
    return [normalize_search_text(part) for part in query.strip().split() if part.strip()]


def normalize_search_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def match_score(entry: SearchEntry, tokens: list[str]) -> int:
    score = 0
    name = entry.name_key or normalize_search_text(entry.name)
    search_text = entry.search_text or normalize_search_text(f"{entry.name}\n{entry.rel}")
    for token in tokens:
        if token not in search_text:
            return 0
        if name == token:
            score += 120
        elif name.startswith(token):
            score += 80
        elif token in name:
            score += 45
        else:
            score += 15
    return score


def search_cache_path(root: Path) -> Path:
    return CACHE_DIR / root_cache_key(root) / INDEX_CACHE_FILE


def cache_entry(entry: SearchEntry) -> dict[str, Any]:
    data = asdict(entry)
    data.pop("root_id", None)
    return data


def search_entry_from_cache(root_id: str, data: Any) -> SearchEntry | None:
    if not isinstance(data, dict):
        return None
    try:
        entry_type = str(data.get("type") or "")
        if entry_type not in {"folder", "media"}:
            return None
        return with_search_keys(SearchEntry(
            root_id=root_id,
            rel=str(data.get("rel") or ""),
            name=str(data.get("name") or Path(str(data.get("rel") or "")).name or root_id),
            type=entry_type,
            size=int(data.get("size") or 0),
            mtime=int(data.get("mtime") or 0),
            preview_rel=str(data.get("preview_rel") or data.get("previewRel") or ""),
            search_text=str(data.get("search_text") or data.get("searchText") or ""),
            name_key=str(data.get("name_key") or data.get("nameKey") or ""),
        ))
    except (TypeError, ValueError):
        return None


def with_search_keys(entry: SearchEntry) -> SearchEntry:
    name_key = entry.name_key or normalize_search_text(entry.name)
    search_text = entry.search_text or normalize_search_text(f"{entry.name}\n{entry.rel}")
    if name_key == entry.name_key and search_text == entry.search_text:
        return entry
    return replace(entry, name_key=name_key, search_text=search_text)


def serialize_entry(entry: SearchEntry) -> dict[str, Any]:
    path = join_rooted_path(entry.root_id, entry.rel)
    result = {
        "root": entry.root_id,
        "rel": entry.rel,
        "name": entry.name,
        "path": path,
        "type": entry.type,
        "size": entry.size,
        "mtime": entry.mtime,
        "folder": entry.rel if entry.type == "folder" else str(Path(entry.rel).parent).replace("\\", "/"),
    }
    if entry.type == "media":
        result["thumbUrl"] = thumb_url(path, "small")
        result["previewPath"] = path
    elif entry.preview_rel:
        preview_path = join_rooted_path(entry.root_id, entry.preview_rel)
        result["thumbUrl"] = thumb_url(preview_path, "small")
        result["previewPath"] = preview_path
    return result
