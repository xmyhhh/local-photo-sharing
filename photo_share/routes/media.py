from __future__ import annotations

import mimetypes

from flask import Flask, jsonify, request

from ..context import AppServices
from ..paths import (
    get_thumbnail_mode,
    image_url,
    preview_url,
    resolve_photo,
    send_cached_file,
    thumb_url,
    to_relative,
)


def register_media_routes(app: Flask, services: AppServices) -> None:
    root = services.root

    @app.get("/api/image/<path:photo_path>")
    def image(photo_path: str):
        path = resolve_photo(root, photo_path)
        return send_cached_file(path, mimetype=mimetypes.guess_type(path.name)[0] or "image/jpeg")

    @app.get("/api/preview/<path:photo_path>")
    def preview(photo_path: str):
        path = resolve_photo(root, photo_path)
        preview_path = services.previews.get_ready(path)
        if preview_path is None:
            services.previews.ensure(path)
            return jsonify({"status": "processing", "url": preview_url(photo_path)}), 202
        return send_cached_file(preview_path, mimetype="image/jpeg")

    @app.get("/api/preview-status/<path:photo_path>")
    def preview_status(photo_path: str):
        path = resolve_photo(root, photo_path)
        error = services.previews.get_error(path)
        if error:
            return jsonify({"status": "error", "url": image_url(photo_path), "error": error}), 500
        preview_path = services.previews.get_ready(path)
        if preview_path is not None:
            return jsonify({"status": "ready", "url": preview_url(photo_path)})
        queued = services.previews.ensure(path)
        return jsonify({"status": "queued" if queued else "processing", "url": preview_url(photo_path)}), 202

    @app.get("/api/download/<path:photo_path>")
    def download(photo_path: str):
        path = resolve_photo(root, photo_path)
        return send_cached_file(
            path,
            mimetype=mimetypes.guess_type(path.name)[0] or "image/jpeg",
            as_attachment=True,
            download_name=path.name,
        )

    @app.get("/api/thumb/<path:photo_path>")
    def thumbnail(photo_path: str):
        path = resolve_photo(root, photo_path)
        mode = get_thumbnail_mode(request.args.get("mode"))
        thumb_store = services.thumbnails[mode]
        thumb = thumb_store.get_ready(path)
        if thumb is None:
            thumb_store.ensure(path)
            return jsonify({"status": "processing", "url": thumb_url(photo_path, mode)}), 202
        return send_cached_file(thumb, mimetype="image/jpeg")

    @app.get("/api/thumb-status/<path:photo_path>")
    def thumbnail_status(photo_path: str):
        path = resolve_photo(root, photo_path)
        mode = get_thumbnail_mode(request.args.get("mode"))
        thumb_store = services.thumbnails[mode]
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
        path = resolve_photo(root, photo_path)
        rel = to_relative(root, path)
        path.unlink()
        services.ratings.delete(rel)
        for thumb_store in services.thumbnails.values():
            thumb_store.delete(path)
        services.previews.delete(path)
        services.metadata.delete(path)
        services.rating_index.delete(rel)
        return jsonify({"deleted": rel})
