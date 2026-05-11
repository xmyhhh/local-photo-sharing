from __future__ import annotations

from flask import Flask, abort, jsonify, request

from ..auth import require_admin, require_path_access
from ..context import AppServices
from ..paths import resolve_photo
from ..ratings import write_embedded_rating
from .gallery import _root_services
from .media import _split_rooted


def register_rating_routes(app: Flask, services: AppServices) -> None:
    @app.get("/api/rating-status/<path:photo_path>")
    def rating_status(photo_path: str):
        require_path_access(services, photo_path)
        root_id, rel = _split_rooted(photo_path)
        root_services = _root_services(services, root_id)
        path = resolve_photo(root_services.root, rel)
        rating_override = root_services.ratings.get_override(rel)
        if rating_override is not None:
            return jsonify({"status": "ready", "rating": rating_override, "source": "user"})
        error = root_services.metadata.get_error(path)
        if error:
            return jsonify({"status": "error", "rating": 0, "error": error}), 500
        if root_services.metadata.is_ready(path):
            return jsonify({"status": "ready", "rating": root_services.metadata.get_rating_ready(path), "source": "embedded"})
        queued = root_services.metadata.ensure(path)
        return jsonify({"status": "queued" if queued else "processing", "rating": 0}), 202

    @app.post("/api/rating/<path:photo_path>")
    def set_rating(photo_path: str):
        require_admin(services)
        root_id, rel = _split_rooted(photo_path)
        root_services = _root_services(services, root_id)
        path = resolve_photo(root_services.root, rel)
        data = request.get_json(silent=True) or {}
        value = data.get("rating")
        if not isinstance(value, int) or value < 0 or value > 5:
            abort(400, "rating must be an integer from 0 to 5")
        try:
            write_embedded_rating(path, value)
        except Exception as error:
            abort(500, f"failed to write JPEG rating: {error}")
        root_services.ratings.set(rel, value)
        root_services.metadata.set_ready(path, value)
        root_services.rating_index.set(rel, value)
        return jsonify({"path": photo_path, "rating": root_services.ratings.get(rel)})
