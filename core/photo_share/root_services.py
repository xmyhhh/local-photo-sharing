from __future__ import annotations

from pathlib import Path

from .constants import CACHE_DIR, DEFAULT_THUMBNAIL_MODE, RATINGS_FILE
from .context import RootServices
from .paths import build_thumbnail_modes, root_cache_key
from .services import FolderCountIndex, ImageCacheStore, MetadataStore, RatingIndex, RatingStore


def create_root_services(
    root: Path,
    thumbnail_mode_settings: dict[str, dict[str, int]] | None,
) -> RootServices:
    root = root.resolve()
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
        previews=thumbnails["xlarge"],
    )
