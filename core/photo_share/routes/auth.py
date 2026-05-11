from __future__ import annotations

from typing import Any

import mimetypes

from flask import Flask, abort, jsonify, request, Response

from ..auth import (
    auth_status_payload,
    ensure_login_background_cache,
    login_background_candidate_paths,
    login_background_gallery,
    login_admin,
    login_guest,
    logout,
    normalize_rooted_path,
    require_admin,
    verify_admin_password,
)
from ..constants import PHOTO_EXTENSIONS
from ..context import AppServices
from ..paths import resolve_media, resolve_photo, send_cached_file
from .media import _split_rooted
from .settings import write_config


def register_auth_routes(app: Flask, services: AppServices) -> None:
    @app.get("/api/auth/status")
    def auth_status():
        return jsonify(auth_status_payload(services))

    @app.post("/api/auth/login")
    def auth_login():
        data = request.get_json(silent=True) or {}
        password = data.get("password", "")
        if not isinstance(password, str):
            abort(400, "password must be a string.")
        if not services.auth.enabled:
            login_admin()
            return jsonify(auth_status_payload(services))
        if verify_admin_password(services, password):
            login_admin()
            return jsonify(auth_status_payload(services))
        return jsonify({"message": "密码不正确。"}), 403

    @app.post("/api/auth/guest")
    def auth_guest():
        if not services.auth.enabled:
            login_admin()
        else:
            login_guest()
        return jsonify(auth_status_payload(services))

    @app.post("/api/auth/logout")
    def auth_logout():
        logout()
        return jsonify(auth_status_payload(services))

    @app.get("/api/auth/background/<path:photo_path>")
    def auth_background(photo_path: str):
        if normalize_rooted_path(photo_path) not in {normalize_rooted_path(item) for item in services.auth.login_backgrounds}:
            abort(403)
        root_id, rel_path = _split_rooted(photo_path)
        root = services.roots.get(root_id)
        if root is None:
            abort(404)
        path = resolve_media(root, rel_path)
        return send_cached_file(path, mimetype=mimetypes.guess_type(path.name)[0] or "application/octet-stream")

    @app.get("/api/auth/background-gallery")
    def auth_background_gallery():
        return jsonify(login_background_gallery(services))

    @app.get("/api/auth/background-thumb/<path:photo_path>")
    def auth_background_thumb(photo_path: str):
        normalized = normalize_rooted_path(photo_path)
        allowed = {normalize_rooted_path(item) for item in login_background_candidate_paths(services)}
        if normalized not in allowed:
            abort(403)
        root_id, rel_path = _split_rooted(normalized)
        root_services = services.root_services.get(root_id)
        if root_services is None:
            abort(404)
        path = resolve_photo(root_services.root, rel_path)
        if path.suffix.lower() not in PHOTO_EXTENSIONS:
            abort(404)
        thumb_store = root_services.thumbnails["medium"]
        thumb = thumb_store.get_ready(path)
        if thumb is None:
            thumb_store.ensure(path)
            return jsonify({"status": "processing"}), 202
        return send_cached_file(thumb, mimetype="image/jpeg")

    @app.get("/api/auth/background-memory/<path:key>")
    def auth_background_memory(key: str):
        data = services.login_background_cache.get(key)
        if data is None:
            ensure_login_background_cache(services)
            data = services.login_background_cache.get(key)
        if data is None:
            abort(404)
        return Response(data, mimetype="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.post("/api/auth/settings")
    def update_auth_settings():
        require_admin(services)
        data = request.get_json(silent=True) or {}
        auth = services.config.setdefault("auth", {})
        if not isinstance(auth, dict):
            auth = {}
            services.config["auth"] = auth

        next_enabled = services.auth.enabled
        next_password = services.auth.password
        if "enabled" in data:
            next_enabled = bool(data["enabled"])
        if "password" in data:
            password = data["password"]
            if not isinstance(password, str):
                abort(400, "password must be a string.")
            next_password = password
        if next_enabled and not next_password:
            abort(400, "启用登录页前必须先设置管理员密码。")

        if "enabled" in data:
            services.auth.enabled = next_enabled
            auth["enabled"] = services.auth.enabled
        if "password" in data:
            services.auth.password = next_password
            auth["password"] = next_password
        if "publicAlbums" in data:
            albums = clean_string_list(data["publicAlbums"], "publicAlbums")
            services.auth.public_albums = {normalize_rooted_path(item) for item in albums if normalize_rooted_path(item)}
            auth["public_albums"] = sorted(services.auth.public_albums)
        if "loginBackgrounds" in data:
            backgrounds = clean_string_list(data["loginBackgrounds"], "loginBackgrounds")
            services.auth.login_backgrounds = backgrounds
            auth["login_backgrounds"] = backgrounds
        if "loginBackgroundMode" in data:
            mode = data["loginBackgroundMode"]
            if mode not in {"none", "rated", "folder"}:
                abort(400, "loginBackgroundMode must be one of none, rated, folder.")
            services.auth.login_background_mode = mode
            auth["login_background_mode"] = mode
        if "loginBackgroundFolder" in data:
            folder = data["loginBackgroundFolder"]
            if not isinstance(folder, str):
                abort(400, "loginBackgroundFolder must be a string.")
            services.auth.login_background_folder = normalize_rooted_path(folder)
            auth["login_background_folder"] = services.auth.login_background_folder
        auth.setdefault("session_secret", services.auth.session_secret)
        write_config(services.config_path, services.config)
        if any(field in data for field in ("loginBackgrounds", "loginBackgroundMode", "loginBackgroundFolder", "publicAlbums")):
            ensure_login_background_cache(services, force=True, async_rebuild=True)
        if services.auth.enabled:
            login_admin()
        return jsonify(auth_status_payload(services))


def clean_string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        abort(400, f"{field} must be an array.")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            abort(400, f"{field} must contain only strings.")
        cleaned = item.strip()
        if cleaned:
            result.append(cleaned)
    return result
