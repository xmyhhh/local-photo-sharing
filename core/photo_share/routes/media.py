from __future__ import annotations

import mimetypes
import os
import shutil
from io import BytesIO
from pathlib import Path

import piexif
from flask import Flask, abort, jsonify, request, send_file
from PIL import Image, ImageOps

from ..constants import PHOTO_EXTENSIONS
from ..context import AppServices
from ..delete_service import delete_media
from ..live_photos import find_live_video
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
        prefetched = services.memory_prefetch.get(path)
        if prefetched is not None:
            response = send_file(
                BytesIO(prefetched.data),
                mimetype=prefetched.mimetype,
                conditional=False,
                download_name=path.name,
            )
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            response.headers["X-Memory-Prefetch"] = "hit"
            return response
        return send_cached_file(path, mimetype=mimetypes.guess_type(path.name)[0] or "application/octet-stream")

    @app.post("/api/prefetch/originals")
    def prefetch_originals():
        data = request.get_json(silent=True) or {}
        client_id = data.get("clientId", "")
        paths = data.get("paths", [])
        if not isinstance(client_id, str) or not client_id:
            abort(400, "clientId must be a non-empty string.")
        if not isinstance(paths, list):
            abort(400, "paths must be an array.")
        resolved: list[Path] = []
        for item in paths:
            if not isinstance(item, str):
                continue
            root_id, rel_path = _split_rooted(item)
            root_services = _root_services(services, root_id)
            try:
                resolved.append(resolve_photo(root_services.root, rel_path))
            except Exception:
                continue
        services.memory_prefetch.prefetch(client_id, resolved)
        return jsonify({"accepted": len(resolved)})

    @app.post("/api/prefetch/release")
    def release_prefetch():
        data = request.get_json(silent=True) or {}
        client_id = data.get("clientId", "")
        if isinstance(client_id, str) and client_id:
            services.memory_prefetch.release(client_id)
        return jsonify({"released": True})

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

    @app.get("/api/info/<path:photo_path>")
    def photo_info(photo_path: str):
        root_id, rel_path = _split_rooted(photo_path)
        root_services = _root_services(services, root_id)
        path = resolve_media(root_services.root, rel_path)
        return jsonify(build_media_info(path))

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
        return jsonify(delete_media(services, root_id, root_services, rel_path, path))

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


def build_media_info(path: Path) -> dict:
    stat = path.stat()
    info = {
        "name": path.name,
        "size": stat.st_size,
        "modified": int(stat.st_mtime),
        "type": path.suffix.lower().lstrip(".").upper(),
        "width": None,
        "height": None,
        "takenAt": None,
        "camera": None,
        "lens": None,
        "exposureTime": None,
        "fNumber": None,
        "iso": None,
        "focalLength": None,
        "exposureBias": None,
    }
    if path.suffix.lower() not in PHOTO_EXTENSIONS:
        return info
    try:
        with Image.open(path) as image:
            info["width"], info["height"] = image.size
    except Exception:
        pass
    try:
        exif = piexif.load(str(path))
    except Exception:
        return info

    zeroth = exif.get("0th", {})
    exif_ifd = exif.get("Exif", {})
    make = _decode_exif_text(zeroth.get(piexif.ImageIFD.Make))
    model = _decode_exif_text(zeroth.get(piexif.ImageIFD.Model))
    lens = _decode_exif_text(exif_ifd.get(piexif.ExifIFD.LensModel))
    taken = (
        _decode_exif_text(exif_ifd.get(piexif.ExifIFD.DateTimeOriginal))
        or _decode_exif_text(exif_ifd.get(piexif.ExifIFD.DateTimeDigitized))
        or _decode_exif_text(zeroth.get(piexif.ImageIFD.DateTime))
    )
    info.update({
        "takenAt": taken,
        "camera": " ".join(item for item in [make, model] if item) or None,
        "lens": lens,
        "exposureTime": _format_exif_rational(exif_ifd.get(piexif.ExifIFD.ExposureTime), reciprocal=True),
        "fNumber": _format_f_number(exif_ifd.get(piexif.ExifIFD.FNumber)),
        "iso": _first_exif_value(
            exif_ifd,
            piexif.ExifIFD.ISOSpeedRatings,
            getattr(piexif.ExifIFD, "PhotographicSensitivity", 34855),
        ),
        "focalLength": _format_mm(exif_ifd.get(piexif.ExifIFD.FocalLength)),
        "exposureBias": _format_ev(exif_ifd.get(piexif.ExifIFD.ExposureBiasValue)),
    })
    return info


def _decode_exif_text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore").strip("\x00 ")
    return str(value).strip()


def _first_exif_value(values: dict, *tags: int):
    for tag in tags:
        value = values.get(tag)
        if value is not None:
            return value
    return None


def _rational_float(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, tuple) and len(value) == 2 and value[1]:
        return float(value[0]) / float(value[1])
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _format_exif_rational(value, reciprocal: bool = False) -> str | None:
    number = _rational_float(value)
    if number is None or number <= 0:
        return None
    if reciprocal and number < 1:
        denominator = round(1 / number)
        return f"1/{denominator}s"
    return f"{number:g}s" if reciprocal else f"{number:g}"


def _format_f_number(value) -> str | None:
    number = _rational_float(value)
    if not number:
        return None
    text = f"{number:.1f}".rstrip("0").rstrip(".")
    return f"f/{text}"


def _format_mm(value) -> str | None:
    number = _rational_float(value)
    if not number:
        return None
    text = f"{number:.1f}".rstrip("0").rstrip(".")
    return f"{text} mm"


def _format_ev(value) -> str | None:
    number = _rational_float(value)
    if number is None:
        return None
    return f"{number:+.1f} EV".replace("+0.0", "0.0")


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
