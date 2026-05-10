from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from flask import Flask, abort, jsonify, request, send_file

from ..constants import (
    FILTER_WAIT_SECONDS,
    JPG_EXTENSIONS,
    PHOTO_EXTENSIONS,
    DEFAULT_ENTRY_PLACEHOLDER_LIMIT,
    RATINGS_FILE,
    STATIC_DIR,
    THUMBNAIL_DIR,
    VIDEO_EXTENSIONS,
)
from ..context import AppServices, RootServices
from ..filters import PhotoFilters, parse_optional_int
from ..live_photos import find_case_insensitive_sibling, find_live_video
from ..paths import (
    join_rooted_path,
    normalize_rel_path,
    parse_rooted_path,
    to_relative,
)


def register_gallery_routes(app: Flask, services: AppServices) -> None:
    @app.get("/")
    def index():
        return send_file(STATIC_DIR / "index.html")

    @app.get("/static/sw.js")
    def service_worker():
        response = send_file(STATIC_DIR / "sw.js", mimetype="application/javascript")
        response.headers["Service-Worker-Allowed"] = "/"
        return response

    @app.get("/api/config")
    def config():
        return jsonify({
            "roots": [
                {"id": root_id, "name": root.name or root_id, "path": str(root.resolve())}
                for root_id, root in services.roots.items()
            ],
            "defaultRootId": services.default_root_id,
            "allowDelete": True,
            "thumbnailQueueLimits": services.thumbnail_queue_limits,
            "uploadPasswordRequired": bool(services.upload_password),
        })

    @app.get("/api/photos")
    def photos():
        root_id = request.args.get("root", "")
        folder = request.args.get("folder", "")
        if not root_id and not folder:
            return jsonify(_virtual_root_payload(services))

        if not root_id:
            root_id, folder = parse_rooted_path(folder)
        root_services = _root_services(services, root_id)
        folder_path = _resolve_rooted_folder(services, root_id, folder)
        filters = PhotoFilters.from_request(request.args)
        cursor = parse_optional_int(request.args.get("cursor"), 0, 1_000_000) or 0
        limit = parse_optional_int(request.args.get("limit"), 1, 50_000) or DEFAULT_ENTRY_PLACEHOLDER_LIMIT
        entries: list[dict[str, Any]] = []
        indexing = False

        if filters.needs_rating:
            root_services.rating_index.index_folder_budget(folder_path, FILTER_WAIT_SECONDS)
            indexing = not root_services.rating_index.is_folder_ready(folder_path)

        next_cursor: int | None = None
        page = _folder_page(folder_path, cursor, limit)
        for seen, child, sibling_map in page["items"]:
            entry = _build_entry(services, root_id, child, root_services, filters, sibling_map)
            if entry is None:
                continue
            entries.append(entry)
            if len(entries) >= limit:
                next_cursor = seen
                break
        if next_cursor is None and page["has_more"]:
            next_cursor = page["next_seen"]

        if filters.needs_rating and indexing:
            root_services.rating_index.ensure_folder_async(folder_path)

        return jsonify({
            "root": root_id,
            "folder": folder,
            "parent": _parent_folder(folder),
            "entries": entries,
            "pendingEntries": [],
            "indexing": indexing,
            "nextCursor": next_cursor,
        })


def _virtual_root_payload(services: AppServices) -> dict[str, Any]:
    entries = [
        _folder_entry(root_services, root_id, "", root_services.root.name or root_id, root_id)
        for root_id, root_services in services.root_services.items()
    ]
    return {
        "root": "",
        "folder": "",
        "parent": "",
        "entries": entries,
        "pendingEntries": [],
        "indexing": False,
        "nextCursor": None,
    }


def _build_entry(
    services: AppServices,
    root_id: str,
    child: Path,
    root_services: RootServices,
    filters: PhotoFilters,
    sibling_map: dict[tuple[str, str], Path] | None = None,
) -> dict[str, Any] | None:
    rel = to_relative(root_services.root, child)
    rooted_path = join_rooted_path(root_id, rel)
    if child.is_dir():
        return _folder_entry(root_services, root_id, rel, child.name, rooted_path)
    suffix = child.suffix.lower()
    if suffix in VIDEO_EXTENSIONS and _has_live_photo_still(child, sibling_map):
        return None
    if suffix in VIDEO_EXTENSIONS:
        stat = child.stat()
        if not filters.matches_photo(0, int(stat.st_mtime)):
            return None
        return {
            "type": "video",
            "name": child.name,
            "path": rooted_path,
            "size": stat.st_size,
            "mtime": int(stat.st_mtime),
            "rating": 0,
            "ratingPending": False,
        }
    if suffix not in PHOTO_EXTENSIONS:
        return None

    stat = child.stat()
    rating, rating_pending = _photo_rating(rel, child, root_services)
    if filters.needs_rating and rating_pending:
        return None
    if not filters.matches_photo(rating, int(stat.st_mtime)):
        return None
    live_video = _find_live_video(child, sibling_map)
    return {
        "type": "photo",
        "name": child.name,
        "path": rooted_path,
        "size": stat.st_size,
        "mtime": int(stat.st_mtime),
        "rating": rating,
        "ratingPending": rating_pending,
        "browserRenderable": suffix in JPG_EXTENSIONS,
        "isLive": live_video is not None,
        "liveVideoPath": join_rooted_path(root_id, to_relative(root_services.root, live_video)) if live_video else None,
    }


def _folder_page(folder_path: Path, cursor: int, limit: int) -> dict[str, Any]:
    dirs: list[Path] = []
    media: list[Path] = []
    sibling_map: dict[tuple[str, str], Path] = {}
    with os.scandir(folder_path) as items:
        for item in items:
            if item.name in {RATINGS_FILE, THUMBNAIL_DIR}:
                continue
            try:
                if item.is_dir():
                    dirs.append(Path(item.path))
                elif item.is_file():
                    path = Path(item.path)
                    suffix = path.suffix.lower()
                    if suffix in PHOTO_EXTENSIONS or suffix in VIDEO_EXTENSIONS:
                        sibling_map[(path.stem.lower(), suffix)] = path
                    if suffix in PHOTO_EXTENSIONS or suffix in VIDEO_EXTENSIONS:
                        media.append(path)
            except OSError:
                continue

    dirs.sort(key=lambda p: p.name.lower())
    media.sort(key=lambda p: p.name.lower())
    items_out: list[tuple[int, Path, dict[tuple[str, str], Path]]] = []
    seen = 0
    for child in [*dirs, *media]:
        seen += 1
        if seen <= cursor:
            continue
        if len(items_out) >= limit:
            return {"items": items_out, "has_more": True, "next_seen": seen - 1}
        items_out.append((seen, child, sibling_map))
    return {"items": items_out, "has_more": False, "next_seen": seen}


def _photo_rating(rel: str, photo_path: Path, root_services: RootServices) -> tuple[int, bool]:
    rating_override = root_services.ratings.get_override(rel)
    if rating_override is not None:
        return rating_override, False

    rating = root_services.metadata.get_rating_ready(photo_path)
    rating_pending = not root_services.metadata.is_ready(photo_path)
    indexed_rating = root_services.rating_index.get(rel)
    if indexed_rating is not None:
        return indexed_rating, False
    return rating, rating_pending


def _folder_entry(root_services: RootServices, root_id: str, rel: str, name: str, rooted_path: str) -> dict[str, Any]:
    folder_path = root_services.root if not rel else root_services.root / rel
    count = root_services.folder_counts.get(folder_path)
    return {
        "type": "folder",
        "name": name,
        "path": rooted_path,
        "photoCount": count,
        "photoCountPending": count is None or not root_services.folder_counts.is_ready(),
    }


def _has_live_photo_still(video_path: Path, sibling_map: dict[tuple[str, str], Path] | None = None) -> bool:
    if video_path.suffix.lower() not in VIDEO_EXTENSIONS:
        return False
    if sibling_map is not None:
        stem = video_path.stem.lower()
        return any((stem, suffix) in sibling_map for suffix in PHOTO_EXTENSIONS)
    return find_case_insensitive_sibling(video_path, PHOTO_EXTENSIONS) is not None


def _find_live_video(photo_path: Path, sibling_map: dict[tuple[str, str], Path] | None = None) -> Path | None:
    if sibling_map is None:
        return find_live_video(photo_path)
    stem = photo_path.stem.lower()
    for suffix in VIDEO_EXTENSIONS:
        video = sibling_map.get((stem, suffix))
        if video is not None:
            return video
    return None


def _resolve_rooted_folder(services: AppServices, root_id: str, folder: str) -> Path:
    root_services = _root_services(services, root_id)
    rel_folder = normalize_rel_path(folder)
    prefix = f"{root_id}/"
    if rel_folder == root_id:
        rel_folder = ""
    elif rel_folder.startswith(prefix):
        rel_folder = rel_folder[len(prefix):]
    path = (root_services.root / rel_folder).resolve()
    try:
        path.relative_to(root_services.root)
    except ValueError:
        abort(403)
    if not path.is_dir():
        abort(404)
    return path


def _root_services(services: AppServices, root_id: str) -> RootServices:
    root_services = services.root_services.get(root_id)
    if root_services is None:
        abort(404)
    return root_services


def _parent_folder(folder: str) -> str:
    if not folder:
        return ""
    parent_path = Path(folder).parent
    return "" if str(parent_path) == "." else parent_path.as_posix()
