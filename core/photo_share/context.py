from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .folder_counts import FolderCountIndex
from .image_cache import ImageCacheStore
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
    roots: dict[str, Path]
    root_services: dict[str, RootServices]
    default_root_id: str
    bracket_tasks: dict[str, dict[str, Any]]
    bracket_cache: dict[str, dict[str, Any]]
    bracket_cache_loaded: bool
    bracket_merge_tasks: dict[str, dict[str, Any]]
    thumbnail_queue_limits: dict[str, int]
    thumbnail_mode_settings: dict[str, dict[str, int]]
    upload_password: str
    enabled_plugins: set[str]
    plugin_assets: list[dict[str, Any]]
    plugin_components: list[dict[str, Any]]
