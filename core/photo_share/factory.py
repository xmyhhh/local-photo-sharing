from __future__ import annotations

from pathlib import Path

from flask import Flask

from .constants import (
    CACHE_DIR,
    DEFAULT_THUMBNAIL_MODE,
    RATINGS_FILE,
    STATIC_DIR,
)
from .context import AppServices, RootServices
from .memory_prefetch import MemoryPrefetchPool, MemoryPrefetchSettings
from .paths import build_thumbnail_modes, root_cache_key
from .plugins import PluginSpec, register_plugins
from .routes import register_routes
from .services import FolderCountIndex, ImageCacheStore, MetadataStore, RatingIndex, RatingStore
from .image_formats import register_image_formats


def create_app(
    photo_roots: list[Path] | Path,
    thumbnail_mode_settings: dict[str, dict[str, int]] | None = None,
    memory_prefetch_settings: MemoryPrefetchSettings | None = None,
    upload_password: str = "",
    plugin_specs: list[PluginSpec] | None = None,
    config: dict | None = None,
    config_path: Path | None = None,
    default_save_folder: Path | None = None,
) -> Flask:
    register_image_formats()
    roots_input = [photo_roots] if isinstance(photo_roots, Path) else photo_roots
    roots = [root.resolve() for root in roots_input]
    if not roots:
        raise ValueError("Photo roots must not be empty.")
    for root in roots:
        if not root.exists() or not root.is_dir():
            raise ValueError(f"Photo root does not exist or is not a folder: {root}")
    default_save = (default_save_folder or roots[0]).resolve()
    default_save.mkdir(parents=True, exist_ok=True)
    if not default_save.is_dir():
        raise ValueError(f"Default save folder is not a folder: {default_save}")
    if not any(_is_relative_to(default_save, root) for root in roots):
        roots.append(default_save)

    app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")
    services = _create_services(
        roots,
        thumbnail_mode_settings,
        memory_prefetch_settings or MemoryPrefetchSettings(),
        upload_password,
        config or {},
        config_path,
        default_save,
    )
    app.config["photo_share_services"] = services
    for root_services in services.root_services.values():
        root_services.folder_counts.ensure_async()
    register_routes(app, services)
    register_plugins(app, services, plugin_specs or [])
    return app


def _create_services(
    roots: list[Path],
    thumbnail_mode_settings: dict[str, dict[str, int]] | None,
    memory_prefetch_settings: MemoryPrefetchSettings,
    upload_password: str,
    config: dict,
    config_path: Path | None,
    default_save_folder: Path,
) -> AppServices:
    root_map = {f"root{index + 1}": root for index, root in enumerate(roots)}
    root_services = {
        root_id: _create_root_services(
            root,
            thumbnail_mode_settings,
        )
        for root_id, root in root_map.items()
    }
    default_save_root_id = next(
        root_id
        for root_id, root in root_map.items()
        if _is_relative_to(default_save_folder, root)
    )
    return AppServices(
        config_path=config_path,
        config=config,
        roots=root_map,
        default_save_root_id=default_save_root_id,
        default_save_folder=default_save_folder,
        root_services=root_services,
        default_root_id="root1",
        bracket_tasks={},
        bracket_cache={},
        bracket_cache_loaded=False,
        bracket_merge_tasks={},
        thumbnail_mode_settings=thumbnail_mode_settings or {},
        upload_password=upload_password,
        memory_prefetch=MemoryPrefetchPool(memory_prefetch_settings),
        enabled_plugins=set(),
        plugin_assets=[],
        plugin_components=[],
        available_plugins=[],
        plugin_modules={},
    )


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _create_root_services(
    root: Path,
    thumbnail_mode_settings: dict[str, dict[str, int]] | None,
) -> RootServices:
    ratings = RatingStore(root / RATINGS_FILE)
    cache_root = CACHE_DIR / root_cache_key(root)
    metadata = MetadataStore(root)
    rating_index = RatingIndex(root, ratings, metadata)
    folder_counts = FolderCountIndex(root)
    thumbnail_modes = build_thumbnail_modes(thumbnail_mode_settings)
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
    return RootServices(
        root=root,
        ratings=ratings,
        metadata=metadata,
        rating_index=rating_index,
        folder_counts=folder_counts,
        thumbnails=thumbnails,
        default_thumbnails=thumbnails[DEFAULT_THUMBNAIL_MODE],
        previews=thumbnails[DEFAULT_THUMBNAIL_MODE],
    )
