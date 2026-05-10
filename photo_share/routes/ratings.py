from __future__ import annotations

from flask import Flask, abort, jsonify, request

from ..context import AppServices
from ..paths import normalize_rel_path, resolve_photo
from ..ratings import write_embedded_rating


def register_rating_routes(app: Flask, services: AppServices) -> None:
    root = services.root

    @app.get("/api/rating-status/<path:photo_path>")
    def rating_status(photo_path: str):
        path = resolve_photo(root, photo_path)
        rel = normalize_rel_path(photo_path)
        rating_override = services.ratings.get_override(rel)
        if rating_override is not None:
            return jsonify({"status": "ready", "rating": rating_override, "source": "user"})
        error = services.metadata.get_error(path)
        if error:
            return jsonify({"status": "error", "rating": 0, "error": error}), 500
        if services.metadata.is_ready(path):
            return jsonify({"status": "ready", "rating": services.metadata.get_rating_ready(path), "source": "embedded"})
        queued = services.metadata.ensure(path)
        return jsonify({"status": "queued" if queued else "processing", "rating": 0}), 202

    @app.post("/api/rating/<path:photo_path>")
    def set_rating(photo_path: str):
        path = resolve_photo(root, photo_path)
        data = request.get_json(silent=True) or {}
        value = data.get("rating")
        if not isinstance(value, int) or value < 0 or value > 5:
            abort(400, "rating must be an integer from 0 to 5")
        rel = normalize_rel_path(photo_path)
        try:
            write_embedded_rating(path, value)
        except Exception as error:
            abort(500, f"failed to write JPEG rating: {error}")
        services.ratings.set(rel, value)
        services.metadata.set_ready(path, value)
        services.rating_index.set(rel, value)
        return jsonify({"path": rel, "rating": services.ratings.get(rel)})
