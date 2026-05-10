from __future__ import annotations

from pathlib import Path

from flask import Flask

from .constants import (
    CACHE_DIR,
    DEFAULT_PREVIEW_QUALITY,
    DEFAULT_PREVIEW_SIZE,
    DEFAULT_THUMBNAIL_MODE,
    PREVIEW_CACHE_QUEUE_LIMIT,
    RATINGS_FILE,
    STATIC_DIR,
)
from .context import AppServices, RootServices
from .paths import build_thumbnail_modes, root_cache_key
from .routes import register_routes
from .services import FolderCountIndex, ImageCacheStore, MetadataStore, RatingIndex, RatingStore
from .image_formats import register_image_formats


def create_app(
    photo_roots: list[Path] | Path,
    preview_size: int = DEFAULT_PREVIEW_SIZE,
    preview_quality: int = DEFAULT_PREVIEW_QUALITY,
    thumbnail_queue_limits: dict[str, int] | None = None,
    thumbnail_mode_settings: dict[str, dict[str, int]] | None = None,
    upload_password: str = "",
) -> Flask:
    register_image_formats()
    roots_input = [photo_roots] if isinstance(photo_roots, Path) else photo_roots
    roots = [root.resolve() for root in roots_input]
    if not roots:
        raise ValueError("Photo roots must not be empty.")
    for root in roots:
        if not root.exists() or not root.is_dir():
            raise ValueError(f"Photo root does not exist or is not a folder: {root}")

    app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")
    services = _create_services(
        roots,
        preview_size,
        preview_quality,
        thumbnail_queue_limits,
        thumbnail_mode_settings,
        upload_password,
    )
    app.config["photo_share_services"] = services
    for root_services in services.root_services.values():
        root_services.folder_counts.ensure_async()
    register_routes(app, services)
    return app


def _create_services(
    roots: list[Path],
    preview_size: int,
    preview_quality: int,
    thumbnail_queue_limits: dict[str, int] | None,
    thumbnail_mode_settings: dict[str, dict[str, int]] | None,
    upload_password: str,
) -> AppServices:
    root_map = {f"root{index + 1}": root for index, root in enumerate(roots)}
    root_services = {
        root_id: _create_root_services(
            root,
            preview_size,
            preview_quality,
            thumbnail_queue_limits,
            thumbnail_mode_settings,
        )
        for root_id, root in root_map.items()
    }
    return AppServices(
        roots=root_map,
        root_services=root_services,
        default_root_id="root1",
        bracket_tasks={},
        bracket_cache={},
        bracket_cache_loaded=False,
        bracket_merge_tasks={},
        thumbnail_queue_limits=thumbnail_queue_limits or {},
        thumbnail_mode_settings=thumbnail_mode_settings or {},
        upload_password=upload_password,
    )


def _create_root_services(
    root: Path,
    preview_size: int,
    preview_quality: int,
    thumbnail_queue_limits: dict[str, int] | None,
    thumbnail_mode_settings: dict[str, dict[str, int]] | None,
) -> RootServices:
    ratings = RatingStore(root / RATINGS_FILE)
    cache_root = CACHE_DIR / root_cache_key(root)
    metadata = MetadataStore(root)
    rating_index = RatingIndex(root, ratings, metadata)
    folder_counts = FolderCountIndex(root)
    thumbnail_modes = build_thumbnail_modes(thumbnail_queue_limits, thumbnail_mode_settings)
    thumbnails = {
        mode: ImageCacheStore(
            root,
            cache_root / f"thumbs_{mode}_{spec['size']}_{spec['quality']}",
            spec["size"],
            spec["quality"],
            f"thumb-{mode}",
            queue_limit=spec["queue_limit"],
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
    return RootServices(
        root=root,
        ratings=ratings,
        metadata=metadata,
        rating_index=rating_index,
        folder_counts=folder_counts,
        thumbnails=thumbnails,
        default_thumbnails=thumbnails[DEFAULT_THUMBNAIL_MODE],
        previews=previews,
    )
