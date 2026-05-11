from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from flask import abort

from .constants import PHOTO_EXTENSIONS, TRASH_DIR, VIDEO_EXTENSIONS
from .context import AppServices, RootServices
from .live_photos import find_case_insensitive_sibling, find_live_video

RECYCLE_PLUGIN_NAME = "recycle_bin"


def delete_media(services: AppServices, root_id: str, root_services: RootServices, rel_path: str, path: Path) -> dict:
    live_video_path = find_live_video(path) if path.suffix.lower() in PHOTO_EXTENSIONS else None
    recycle_enabled = is_recycle_bin_enabled(services)
    counted_media_deleted = is_counted_media(path)
    deleted_items: list[dict] = []

    if live_video_path is not None:
        deleted_items.append(delete_path(services, root_id, root_services.root, live_video_path, recycle_enabled))
    deleted_items.append(delete_path(services, root_id, root_services.root, path, recycle_enabled))

    cleanup_photo_indexes(root_services, rel_path, path)
    if counted_media_deleted:
        root_services.folder_counts.decrement_deleted_media(path)

    return {
        "deleted": f"{root_id}/{rel_path}",
        "mode": "recycle" if recycle_enabled else "permanent",
        "items": deleted_items,
        "liveVideoDeleted": live_video_path is None or any(item["source"].lower().endswith(live_video_path.name.lower()) for item in deleted_items),
    }


def delete_item(services: AppServices, root_id: str, root_services: RootServices, path: Path) -> dict:
    recycle_enabled = is_recycle_bin_enabled(services)
    result = delete_path(services, root_id, root_services.root, path, recycle_enabled)
    root_services.folder_counts.refresh_subtree_async(path.parent)
    return result


def delete_path(services: AppServices, root_id: str, root: Path, path: Path, recycle_enabled: bool) -> dict:
    if recycle_enabled:
        trashed = move_to_trash(path, root, root_id)
        record = {
            "id": uuid4().hex,
            "rootId": root_id,
            "originalRel": path.resolve().relative_to(root).as_posix(),
            "originalName": path.name,
            "trashPath": str(trashed),
            "isDir": trashed.is_dir(),
            "deletedAt": datetime.now().isoformat(timespec="seconds"),
            "size": directory_size(trashed) if trashed.is_dir() else trashed.stat().st_size,
        }
        recorder = getattr(services, "recycle_bin_recorder", None)
        if callable(recorder):
            recorder(record)
        return {"source": str(path), "trashed": str(trashed), "recycled": True, "id": record["id"]}

    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return {"source": str(path), "recycled": False}


def cleanup_photo_indexes(root_services: RootServices, rel_path: str, path: Path) -> None:
    if path.suffix.lower() not in PHOTO_EXTENSIONS:
        return
    root_services.ratings.delete(rel_path)
    for thumb_store in root_services.thumbnails.values():
        thumb_store.delete(path)
    root_services.previews.delete(path)
    root_services.metadata.delete(path)
    root_services.rating_index.delete(rel_path)


def is_recycle_bin_enabled(services: AppServices) -> bool:
    return RECYCLE_PLUGIN_NAME in services.enabled_plugins


def is_counted_media(path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix in VIDEO_EXTENSIONS and find_case_insensitive_sibling(path, PHOTO_EXTENSIONS) is not None:
        return False
    return True


def move_to_trash(path: Path, root: Path, root_id: str) -> Path:
    rel = path.resolve().relative_to(root)
    target_dir = TRASH_DIR / root_id / rel.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    target = unique_trash_path(target_dir / path.name)
    try:
        os.replace(path, target)
    except OSError as error:
        if getattr(error, "winerror", None) != 17 and getattr(error, "errno", None) != 18:
            raise
        shutil.move(str(path), str(target))
    return target


def unique_trash_path(path: Path) -> Path:
    if not path.exists():
        return path
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for index in range(1, 10_000):
        candidate = path.with_name(f"{path.stem}_{timestamp}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    abort(409, "Too many duplicate files in trash.")


def directory_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total
