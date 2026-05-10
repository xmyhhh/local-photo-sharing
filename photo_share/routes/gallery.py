from __future__ import annotations

from pathlib import Path
from typing import Any

from flask import Flask, abort, jsonify, request, send_file

from ..constants import (
    FILTER_WAIT_SECONDS,
    JPG_EXTENSIONS,
    MEDIA_EXTENSIONS,
    PHOTO_EXTENSIONS,
    PHOTO_PAGE_SIZE,
    RATINGS_FILE,
    STATIC_DIR,
    THUMBNAIL_DIR,
    VIDEO_EXTENSIONS,
)
from ..context import AppServices, RootServices
from ..filters import PhotoFilters, parse_optional_int
from ..live_photos import find_case_insensitive_sibling, find_live_video
from ..paths import (
    iter_folder_children,
    join_rooted_path,
    normalize_rel_path,
    parse_rooted_path,
    to_relative,
)


def register_gallery_routes(app: Flask, services: AppServices) -> None:
    @app.get("/")
    def index():
        return send_file(STATIC_DIR / "index.html")

    @app.get("/api/config")
    def config():
        return jsonify({
            "roots": [
                {"id": root_id, "path": str(root.resolve())}
                for root_id, root in services.roots.items()
            ],
            "defaultRootId": services.default_root_id,
            "allowDelete": True,
            "thumbnailQueueLimits": services.thumbnail_queue_limits,
        })

    @app.get("/api/photos")
    def photos():
        root_id = request.args.get("root", services.default_root_id)
        root_services = _root_services(services, root_id)
        folder = request.args.get("folder", "")
        folder_path = _resolve_rooted_folder(services, root_id, folder)
        filters = PhotoFilters.from_request(request.args)
        cursor = parse_optional_int(request.args.get("cursor"), 0, 1_000_000) or 0
        limit = parse_optional_int(request.args.get("limit"), 1, 300) or PHOTO_PAGE_SIZE
        entries: list[dict[str, Any]] = []
        indexing = False

        if filters.needs_rating:
            root_services.rating_index.index_folder_budget(folder_path, FILTER_WAIT_SECONDS)
            indexing = not root_services.rating_index.is_folder_ready(folder_path)

        seen = 0
        next_cursor: int | None = None
        for child in iter_folder_children(folder_path):
            if child.name in {RATINGS_FILE, THUMBNAIL_DIR}:
                continue
            if seen < cursor:
                seen += 1
                continue

            entry = _build_entry(services, root_id, child, root_services, filters)
            seen += 1
            if entry is None:
                continue
            entries.append(entry)
            if len(entries) >= limit:
                next_cursor = seen
                break

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


def _build_entry(
    services: AppServices,
    root_id: str,
    child: Path,
    root_services: RootServices,
    filters: PhotoFilters,
) -> dict[str, Any] | None:
    rel = to_relative(root_services.root, child)
    rooted_path = join_rooted_path(root_id, rel)
    if child.is_dir():
        return {
            "type": "folder",
            "name": child.name,
            "path": rooted_path,
            "photoCount": _count_photos_recursive(child),
        }
    suffix = child.suffix.lower()
    if suffix in VIDEO_EXTENSIONS and _has_live_photo_still(child):
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
    live_video = find_live_video(child)
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


def _count_photos_recursive(folder_path: Path) -> int:
    count = 0
    stack = [folder_path]
    while stack:
        current = stack.pop()
        try:
            children = list(current.iterdir())
        except OSError:
            continue
        for child in children:
            if child.name in {RATINGS_FILE, THUMBNAIL_DIR}:
                continue
            if child.is_dir():
                stack.append(child)
            elif child.is_file() and child.suffix.lower() in MEDIA_EXTENSIONS:
                if child.suffix.lower() in VIDEO_EXTENSIONS and _has_live_photo_still(child):
                    continue
                count += 1
    return count


def _has_live_photo_still(video_path: Path) -> bool:
    if video_path.suffix.lower() not in VIDEO_EXTENSIONS:
        return False
    return find_case_insensitive_sibling(video_path, PHOTO_EXTENSIONS) is not None


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
