from __future__ import annotations

from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request, send_file

from ..constants import (
    FILTER_WAIT_SECONDS,
    JPG_EXTENSIONS,
    PHOTO_PAGE_SIZE,
    RATINGS_FILE,
    STATIC_DIR,
    THUMBNAIL_DIR,
)
from ..context import AppServices
from ..filters import PhotoFilters, parse_optional_int
from ..paths import iter_folder_children, resolve_folder, to_relative


def register_gallery_routes(app: Flask, services: AppServices) -> None:
    root = services.root

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
        cursor = parse_optional_int(request.args.get("cursor"), 0, 1_000_000) or 0
        limit = parse_optional_int(request.args.get("limit"), 1, 300) or PHOTO_PAGE_SIZE
        entries: list[dict[str, Any]] = []
        indexing = False

        if filters.needs_rating:
            services.rating_index.index_folder_budget(folder_path, FILTER_WAIT_SECONDS)
            indexing = not services.rating_index.is_folder_ready(folder_path)

        seen = 0
        next_cursor: int | None = None
        for child in iter_folder_children(folder_path):
            if child.name in {RATINGS_FILE, THUMBNAIL_DIR}:
                continue
            if seen < cursor:
                seen += 1
                continue

            entry = _build_entry(root, child, services, filters)
            seen += 1
            if entry is None:
                continue
            entries.append(entry)
            if len(entries) >= limit:
                next_cursor = seen
                break

        if filters.needs_rating and indexing:
            services.rating_index.ensure_folder_async(folder_path)

        return jsonify({
            "folder": folder,
            "parent": _parent_folder(folder),
            "entries": entries,
            "pendingEntries": [],
            "indexing": indexing,
            "nextCursor": next_cursor,
        })


def _build_entry(
    root: Path,
    child: Path,
    services: AppServices,
    filters: PhotoFilters,
) -> dict[str, Any] | None:
    rel = to_relative(root, child)
    if child.is_dir():
        return {"type": "folder", "name": child.name, "path": rel}
    if child.suffix.lower() not in JPG_EXTENSIONS:
        return None

    stat = child.stat()
    rating, rating_pending = _photo_rating(rel, child, services)
    if filters.needs_rating and rating_pending:
        return None
    if not filters.matches_photo(rating, int(stat.st_mtime)):
        return None
    return {
        "type": "photo",
        "name": child.name,
        "path": rel,
        "size": stat.st_size,
        "mtime": int(stat.st_mtime),
        "rating": rating,
        "ratingPending": rating_pending,
    }


def _photo_rating(rel: str, photo_path: Path, services: AppServices) -> tuple[int, bool]:
    rating_override = services.ratings.get_override(rel)
    if rating_override is not None:
        return rating_override, False

    rating = services.metadata.get_rating_ready(photo_path)
    rating_pending = not services.metadata.is_ready(photo_path)
    indexed_rating = services.rating_index.get(rel)
    if indexed_rating is not None:
        return indexed_rating, False
    return rating, rating_pending


def _parent_folder(folder: str) -> str:
    if not folder:
        return ""
    parent_path = Path(folder).parent
    return "" if str(parent_path) == "." else parent_path.as_posix()
