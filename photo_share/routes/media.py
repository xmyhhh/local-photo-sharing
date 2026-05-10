from __future__ import annotations

import mimetypes

from flask import Flask, jsonify, request

from ..constants import JPG_EXTENSIONS
from ..context import AppServices
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
        error = root_services.previews.get_error(path)
        if error:
            return jsonify({"status": "error", "url": image_url(photo_path), "error": error}), 500
        preview_path = root_services.previews.get_ready(path)
        if preview_path is not None:
            return jsonify({"status": "ready", "url": preview_url(photo_path)})
        queued = root_services.previews.ensure(path)
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
        error = thumb_store.get_error(path)
        if error:
            return jsonify({"status": "error", "url": image_url(photo_path), "error": error}), 500
        thumb = thumb_store.get_ready(path)
        if thumb is not None:
            return jsonify({"status": "ready", "url": thumb_url(photo_path, mode)})
        queued = thumb_store.ensure(path)
        return jsonify({"status": "queued" if queued else "processing", "url": thumb_url(photo_path, mode)}), 202

    @app.delete("/api/photo/<path:photo_path>")
    def delete_photo(photo_path: str):
        root_id, rel_path = _split_rooted(photo_path)
        root_services = _root_services(services, root_id)
        path = resolve_media(root_services.root, rel_path)
        rel = rel_path
        path.unlink()
        root_services.ratings.delete(rel)
        if path.suffix.lower() in JPG_EXTENSIONS:
            for thumb_store in root_services.thumbnails.values():
                thumb_store.delete(path)
            root_services.previews.delete(path)
            root_services.metadata.delete(path)
            root_services.rating_index.delete(rel)
        return jsonify({"deleted": f"{root_id}/{rel}"})


def _split_rooted(value: str) -> tuple[str, str]:
    parts = value.split("/", 1)
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]
