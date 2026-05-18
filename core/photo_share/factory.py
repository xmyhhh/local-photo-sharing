from __future__ import annotations

from pathlib import Path
import secrets
from threading import Lock

from flask import Flask

from .constants import (
    DEFAULT_SAMPLE_GALLERY_DIR,
    STATIC_DIR,
)
from .context import AppServices, AuthSettings, RootServices
from .memory_prefetch import MemoryPrefetchPool, MemoryPrefetchSettings
from .plugins import PluginSpec, register_plugins
from .root_services import create_root_services
from .routes import register_routes
from .sample_gallery import install_sample_gallery_if_available
from .image_formats import register_image_formats


def create_app(
    photo_roots: list[Path] | Path,
    thumbnail_mode_settings: dict[str, dict[str, int]] | None = None,
    memory_prefetch_settings: MemoryPrefetchSettings | None = None,
    upload_password: str = "",
    plugin_specs: list[PluginSpec] | None = None,
    config: dict | None = None,
    config_path: Path | None = None,
    default_save_folder: Path | None = None,
) -> Flask:
    register_image_formats()
    roots_input = [photo_roots] if isinstance(photo_roots, Path) else photo_roots
    roots = [root.resolve() for root in roots_input]
    if not roots:
        raise ValueError("Photo roots must not be empty.")
    for root in roots:
        if not root.exists() or not root.is_dir():
            raise ValueError(f"Photo root does not exist or is not a folder: {root}")
    default_save = (default_save_folder or roots[0]).resolve()
    default_save.mkdir(parents=True, exist_ok=True)
    if not default_save.is_dir():
        raise ValueError(f"Default save folder is not a folder: {default_save}")
    if not any(_is_relative_to(default_save, root) for root in roots):
        roots.append(default_save)

    app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")
    app.secret_key = _session_secret(config or {}, config_path)
    services = _create_services(
        roots,
        thumbnail_mode_settings,
        memory_prefetch_settings or MemoryPrefetchSettings(),
        upload_password,
        config or {},
        config_path,
        default_save,
    )
    install_sample_gallery_if_available(services, DEFAULT_SAMPLE_GALLERY_DIR)
    app.config["photo_share_services"] = services
    register_routes(app, services)
    register_plugins(app, services, plugin_specs or [])
    return app


def _create_services(
    roots: list[Path],
    thumbnail_mode_settings: dict[str, dict[str, int]] | None,
    memory_prefetch_settings: MemoryPrefetchSettings,
    upload_password: str,
    config: dict,
    config_path: Path | None,
    default_save_folder: Path,
) -> AppServices:
    root_map = {f"root{index + 1}": root for index, root in enumerate(roots)}
    root_services = {
        root_id: _create_root_services(
            root,
            thumbnail_mode_settings,
        )
        for root_id, root in root_map.items()
    }
    default_save_root_id = next(
        root_id
        for root_id, root in root_map.items()
        if _is_relative_to(default_save_folder, root)
    )
    return AppServices(
        config_path=config_path,
        config=config,
        roots=root_map,
        default_save_root_id=default_save_root_id,
        default_save_folder=default_save_folder,
        root_services=root_services,
        default_root_id="root1",
        bracket_tasks={},
        bracket_cache={},
        bracket_cache_loaded=False,
        bracket_merge_tasks={},
        zip_tasks={},
        thumbnail_mode_settings=thumbnail_mode_settings or {},
        upload_password=upload_password,
        auth=_build_auth_settings(config),
        memory_prefetch=MemoryPrefetchPool(memory_prefetch_settings),
        enabled_plugins=set(),
        plugin_assets=[],
        plugin_components=[],
        available_plugins=[],
        plugin_modules={},
        recycle_bin_recorder=None,
        warmup_status=None,
        login_background_provider=None,
        login_background_cache={},
        login_background_items=[],
        login_background_cache_key="",
        login_background_refreshing=False,
        login_background_lock=Lock(),
    )


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _build_auth_settings(config: dict) -> AuthSettings:
    auth = config.get("auth", {})
    if not isinstance(auth, dict):
        auth = {}
    return AuthSettings(
        enabled=bool(auth.get("enabled", False)),
        password=str(auth.get("password") or ""),
        session_secret=str(auth.get("session_secret") or ""),
        public_albums={_normalize_config_path(item) for item in auth.get("public_albums", []) if isinstance(item, str)},
        login_backgrounds=[item.strip() for item in auth.get("login_backgrounds", []) if isinstance(item, str) and item.strip()],
        login_background_mode=_login_background_mode(auth.get("login_background_mode")),
        login_background_folder=_normalize_config_path(str(auth.get("login_background_folder") or "")),
        login_background_layout=_login_background_layout(auth.get("login_background_layout")),
    )


def _normalize_config_path(value: str) -> str:
    return "/".join(part for part in value.replace("\\", "/").strip("/ ").split("/") if part)


def _login_background_mode(value: object) -> str:
    return value if value in {"none", "rated", "folder"} else "none"


def _login_background_layout(value: object) -> str:
    return value if value in {"grid", "stack", "solo"} else "grid"


def _session_secret(config: dict, config_path: Path | None) -> str:
    auth = config.get("auth", {}) if isinstance(config, dict) else {}
    if isinstance(auth, dict) and isinstance(auth.get("session_secret"), str) and auth["session_secret"]:
        return auth["session_secret"]
    seed = f"{config_path or ''}|{auth.get('password', '') if isinstance(auth, dict) else ''}"
    return seed or secrets.token_hex(32)


def _create_root_services(
    root: Path,
    thumbnail_mode_settings: dict[str, dict[str, int]] | None,
) -> RootServices:
    return create_root_services(root, thumbnail_mode_settings)
