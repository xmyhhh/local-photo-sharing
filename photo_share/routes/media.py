from __future__ import annotations

import mimetypes
import os
from datetime import datetime
from pathlib import Path

import piexif
from flask import Flask, abort, jsonify, request
from PIL import Image, ImageOps

from ..constants import PHOTO_EXTENSIONS, TRASH_DIR, VIDEO_EXTENSIONS
from ..context import AppServices
from ..live_photos import find_case_insensitive_sibling, find_live_video
from ..paths import (
    get_thumbnail_mode,
    image_url,
    preview_url,
    resolve_media,
    resolve_photo,
    send_cached_file,
    thumb_url,
)
from .gallery import _root_services


def register_media_routes(app: Flask, services: AppServices) -> None:
    @app.get("/api/image/<path:photo_path>")
    def image(photo_path: str):
        root_id, rel_path = _split_rooted(photo_path)
        root_services = _root_services(services, root_id)
        path = resolve_media(root_services.root, rel_path)
        return send_cached_file(path, mimetype=mimetypes.guess_type(path.name)[0] or "application/octet-stream")

    @app.get("/api/preview/<path:photo_path>")
    def preview(photo_path: str):
        root_id, rel_path = _split_rooted(photo_path)
        root_services = _root_services(services, root_id)
        path = resolve_photo(root_services.root, rel_path)
        preview_path = root_services.previews.get_ready(path)
        if preview_path is None:
            root_services.previews.ensure(path)
            return jsonify({"status": "processing", "url": preview_url(photo_path)}), 202
        return send_cached_file(preview_path, mimetype="image/jpeg")

    @app.get("/api/preview-status/<path:photo_path>")
    def preview_status(photo_path: str):
        root_id, rel_path = _split_rooted(photo_path)
        root_services = _root_services(services, root_id)
        path = resolve_photo(root_services.root, rel_path)
        preview_path = root_services.previews.get_ready(path)
        if preview_path is not None:
            return jsonify({"status": "ready", "url": preview_url(photo_path)})
        queued = root_services.previews.ensure(path)
        error = root_services.previews.get_error(path)
        if error and not queued:
            return jsonify({"status": "error", "url": preview_url(photo_path), "error": error}), 500
        return jsonify({"status": "queued" if queued else "processing", "url": preview_url(photo_path)}), 202

    @app.get("/api/download/<path:photo_path>")
    def download(photo_path: str):
        root_id, rel_path = _split_rooted(photo_path)
        root_services = _root_services(services, root_id)
        path = resolve_media(root_services.root, rel_path)
        return send_cached_file(
            path,
            mimetype=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            as_attachment=True,
            download_name=path.name,
        )

    @app.get("/api/live-video/<path:photo_path>")
    def live_video(photo_path: str):
        root_id, rel_path = _split_rooted(photo_path)
        root_services = _root_services(services, root_id)
        photo = resolve_photo(root_services.root, rel_path)
        video = find_live_video(photo)
        if video is None:
            abort(404)
        return send_cached_file(video, mimetype=mimetypes.guess_type(video.name)[0] or "video/quicktime")

    @app.get("/api/thumb/<path:photo_path>")
    def thumbnail(photo_path: str):
        root_id, rel_path = _split_rooted(photo_path)
        root_services = _root_services(services, root_id)
        path = resolve_photo(root_services.root, rel_path)
        mode = get_thumbnail_mode(request.args.get("mode"))
        thumb_store = root_services.thumbnails[mode]
        thumb = thumb_store.get_ready(path)
        if thumb is None:
            thumb_store.ensure(path)
            return jsonify({"status": "processing", "url": thumb_url(photo_path, mode)}), 202
        return send_cached_file(thumb, mimetype="image/jpeg")

    @app.get("/api/thumb-status/<path:photo_path>")
    def thumbnail_status(photo_path: str):
        root_id, rel_path = _split_rooted(photo_path)
        root_services = _root_services(services, root_id)
        path = resolve_photo(root_services.root, rel_path)
        mode = get_thumbnail_mode(request.args.get("mode"))
        thumb_store = root_services.thumbnails[mode]
        thumb = thumb_store.get_ready(path)
        if thumb is not None:
            return jsonify({"status": "ready", "url": thumb_url(photo_path, mode)})
        queued = thumb_store.ensure(path)
        error = thumb_store.get_error(path)
        if error and not queued:
            return jsonify({"status": "error", "url": thumb_url(photo_path, mode), "error": error}), 500
        return jsonify({"status": "queued" if queued else "processing", "url": thumb_url(photo_path, mode)}), 202

    @app.delete("/api/photo/<path:photo_path>")
    def delete_photo(photo_path: str):
        root_id, rel_path = _split_rooted(photo_path)
        root_services = _root_services(services, root_id)
        path = resolve_media(root_services.root, rel_path)
        rel = rel_path
        live_video_path = find_live_video(path) if path.suffix.lower() in PHOTO_EXTENSIONS else None
        live_delete_failed = False
        if live_video_path is not None:
            try:
                move_to_trash(live_video_path, root_services.root, root_id)
            except OSError:
                live_delete_failed = True
        counted_media_deleted = _is_counted_media(path)
        trashed_path = move_to_trash(path, root_services.root, root_id)
        root_services.ratings.delete(rel)
        if path.suffix.lower() in PHOTO_EXTENSIONS:
            for thumb_store in root_services.thumbnails.values():
                thumb_store.delete(path)
            root_services.previews.delete(path)
            root_services.metadata.delete(path)
            root_services.rating_index.delete(rel)
        if counted_media_deleted:
            root_services.folder_counts.decrement_deleted_media(path)
        return jsonify({
            "deleted": f"{root_id}/{rel}",
            "trashed": str(trashed_path),
            "liveVideoDeleted": not live_delete_failed,
        })

    @app.post("/api/rotate/<path:photo_path>")
    def rotate_photo(photo_path: str):
        root_id, rel_path = _split_rooted(photo_path)
        root_services = _root_services(services, root_id)
        path = resolve_photo(root_services.root, rel_path)
        data = request.get_json(silent=True) or {}
        direction = data.get("direction", "right")
        if direction not in {"left", "right"}:
            abort(400, "direction must be left or right")

        _rotate_jpeg_file(path, -90 if direction == "right" else 90)
        for thumb_store in root_services.thumbnails.values():
            thumb_store.delete(path)
        root_services.previews.delete(path)
        root_services.metadata.delete(path)
        rating = root_services.ratings.get_override(rel_path)
        if rating is not None:
            root_services.metadata.set_ready(path, rating)
            root_services.rating_index.set(rel_path, rating, path)
        stat = path.stat()
        return jsonify({
            "path": f"{root_id}/{rel_path}",
            "mtime": int(stat.st_mtime),
            "imageUrl": image_url(photo_path),
            "thumbUrl": thumb_url(photo_path),
            "previewUrl": preview_url(photo_path),
        })


def _split_rooted(value: str) -> tuple[str, str]:
    parts = value.split("/", 1)
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


def _is_counted_media(path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix in VIDEO_EXTENSIONS and find_case_insensitive_sibling(path, PHOTO_EXTENSIONS) is not None:
        return False
    return True


def move_to_trash(path: Path, root: Path, root_id: str) -> Path:
    rel = path.resolve().relative_to(root)
    target_dir = TRASH_DIR / root_id / rel.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    target = unique_trash_path(target_dir / path.name)
    os.replace(path, target)
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


def _rotate_jpeg_file(path: Path, angle: int) -> None:
    tmp_path = path.with_name(f".{path.name}.rotate.tmp")
    try:
        with Image.open(path) as image:
            exif_bytes = _rotated_exif_bytes(path)
            rotated = ImageOps.exif_transpose(image).rotate(angle, expand=True)
            if rotated.mode not in {"RGB", "L"}:
                rotated = rotated.convert("RGB")
            save_kwargs = {"format": "JPEG", "quality": 95, "optimize": True}
            if exif_bytes:
                save_kwargs["exif"] = exif_bytes
            rotated.save(tmp_path, **save_kwargs)
        os.replace(tmp_path, path)
    except Exception as error:
        if tmp_path.exists():
            tmp_path.unlink()
        abort(500, f"failed to rotate JPEG: {error}")


def _rotated_exif_bytes(path: Path) -> bytes:
    try:
        exif_dict = piexif.load(str(path))
    except Exception as error:
        abort(500, f"failed to read JPEG EXIF: {error}")
    exif_dict.setdefault("0th", {}).pop(piexif.ImageIFD.Orientation, None)
    _normalize_exif_value_types(exif_dict)
    return piexif.dump(exif_dict)


def _normalize_exif_value_types(exif_dict: dict) -> None:
    for ifd_name in ("0th", "Exif", "GPS", "Interop", "1st"):
        ifd = exif_dict.get(ifd_name)
        if not isinstance(ifd, dict):
            continue
        tags = piexif.TAGS.get(ifd_name, {})
        for tag, value in list(ifd.items()):
            tag_type = tags.get(tag, {}).get("type")
            if tag_type == 7 and isinstance(value, int):
                if 0 <= value <= 255:
                    ifd[tag] = bytes([value])
                else:
                    length = max(1, (value.bit_length() + 7) // 8)
                    ifd[tag] = value.to_bytes(length, "big", signed=False)
