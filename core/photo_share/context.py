from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .folder_counts import FolderCountIndex
from .image_cache import ImageCacheStore
from .memory_prefetch import MemoryPrefetchPool
from .rating_index import RatingIndex
from .stores import MetadataStore, RatingStore


@dataclass
class RootServices:
    root: Path
    ratings: RatingStore
    metadata: MetadataStore
    rating_index: RatingIndex
    folder_counts: FolderCountIndex
    thumbnails: dict[str, ImageCacheStore]
    default_thumbnails: ImageCacheStore
    previews: ImageCacheStore


@dataclass
class AppServices:
    config_path: Path | None
    config: dict[str, Any]
    roots: dict[str, Path]
    default_save_root_id: str
    default_save_folder: Path
    root_services: dict[str, RootServices]
    default_root_id: str
    bracket_tasks: dict[str, dict[str, Any]]
    bracket_cache: dict[str, dict[str, Any]]
    bracket_cache_loaded: bool
    bracket_merge_tasks: dict[str, dict[str, Any]]
    thumbnail_mode_settings: dict[str, dict[str, int]]
    upload_password: str
    memory_prefetch: MemoryPrefetchPool
    enabled_plugins: set[str]
    plugin_assets: list[dict[str, Any]]
    plugin_components: list[dict[str, Any]]
    available_plugins: list[dict[str, Any]]
    plugin_modules: dict[str, Any]
    recycle_bin_recorder: Any | None
    warmup_status: Any | None
