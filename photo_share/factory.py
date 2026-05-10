from __future__ import annotations

from pathlib import Path

from flask import Flask

from .constants import (
    CACHE_DIR,
    DEFAULT_PREVIEW_QUALITY,
    DEFAULT_PREVIEW_SIZE,
    DEFAULT_THUMBNAIL_MODE,
    DEFAULT_THUMBNAIL_QUALITY,
    DEFAULT_THUMBNAIL_SIZE,
    PREVIEW_CACHE_QUEUE_LIMIT,
    RATINGS_FILE,
    STATIC_DIR,
    THUMB_CACHE_QUEUE_LIMIT,
)
from .context import AppServices
from .paths import build_thumbnail_modes, root_cache_key
from .routes import register_routes
from .services import ImageCacheStore, MetadataStore, RatingIndex, RatingStore


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
    services = _create_services(root, thumbnail_size, thumbnail_quality, preview_size, preview_quality)
    register_routes(app, services)
    return app


def _create_services(
    root: Path,
    thumbnail_size: int,
    thumbnail_quality: int,
    preview_size: int,
    preview_quality: int,
) -> AppServices:
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
    previews = ImageCacheStore(
        root,
        cache_root / f"previews_{preview_size}_{preview_quality}",
        preview_size,
        preview_quality,
        "preview",
        queue_limit=PREVIEW_CACHE_QUEUE_LIMIT,
    )
    return AppServices(
        root=root,
        ratings=ratings,
        metadata=metadata,
        rating_index=rating_index,
        thumbnails=thumbnails,
        default_thumbnails=thumbnails[DEFAULT_THUMBNAIL_MODE],
        previews=previews,
    )
