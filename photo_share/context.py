from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .image_cache import ImageCacheStore
from .rating_index import RatingIndex
from .stores import MetadataStore, RatingStore


@dataclass
class AppServices:
    root: Path
    ratings: RatingStore
    metadata: MetadataStore
    rating_index: RatingIndex
    thumbnails: dict[str, ImageCacheStore]
    default_thumbnails: ImageCacheStore
    previews: ImageCacheStore
    bracket_tasks: dict[str, dict[str, Any]]
