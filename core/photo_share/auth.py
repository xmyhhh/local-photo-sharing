from __future__ import annotations

from hmac import compare_digest
from urllib.parse import urlparse

from flask import abort, session

from .context import AppServices
from .paths import normalize_rel_path, parse_rooted_path, quote_path

ROLE_ADMIN = "admin"
ROLE_GUEST = "guest"


def auth_enabled(services: AppServices) -> bool:
    return bool(services.auth.enabled)


def current_role(services: AppServices) -> str:
    if not auth_enabled(services):
        return ROLE_ADMIN
    role = session.get("photo_share_role")
    return role if role in {ROLE_ADMIN, ROLE_GUEST} else ""


def is_admin(services: AppServices) -> bool:
    return current_role(services) == ROLE_ADMIN


def is_guest(services: AppServices) -> bool:
    return current_role(services) == ROLE_GUEST


def require_admin(services: AppServices) -> None:
    if is_admin(services):
        return
    abort(401 if not current_role(services) else 403)


def require_authenticated(services: AppServices) -> None:
    if current_role(services):
        return
    abort(401)


def verify_admin_password(services: AppServices, password: str) -> bool:
    return bool(services.auth.password) and compare_digest(password, services.auth.password)


def login_admin() -> None:
    session["photo_share_role"] = ROLE_ADMIN


def login_guest() -> None:
    session["photo_share_role"] = ROLE_GUEST


def logout() -> None:
    session.pop("photo_share_role", None)


def require_path_access(services: AppServices, rooted_path: str) -> None:
    if is_admin(services):
        return
    if is_guest(services) and is_public_path(services, rooted_path):
        return
    abort(401 if not current_role(services) else 403)


def require_guest_delete_access(services: AppServices, rooted_path: str) -> None:
    if is_admin(services):
        return
    if is_guest(services) and is_public_path(services, rooted_path):
        return
    abort(401 if not current_role(services) else 403)


def require_folder_access(services: AppServices, root_id: str, folder: str) -> None:
    if is_admin(services):
        return
    rooted_path = join_rooted(root_id, folder)
    if is_guest(services) and is_public_or_ancestor(services, rooted_path):
        return
    abort(401 if not current_role(services) else 403)


def visible_roots(services: AppServices) -> list[dict[str, str]]:
    if is_admin(services):
        return [
            {"id": root_id, "name": root.name or root_id, "path": str(root.resolve())}
            for root_id, root in services.roots.items()
        ]
    if is_guest(services):
        root_ids = []
        for rooted_path in sorted(services.auth.public_albums, key=str.lower):
            try:
                root_id, _rel = parse_rooted_path(rooted_path)
            except Exception:
                continue
            if root_id in services.roots and root_id not in root_ids:
                root_ids.append(root_id)
        return [
            {"id": root_id, "name": services.roots[root_id].name or root_id, "path": str(services.roots[root_id].resolve())}
            for root_id in root_ids
        ]
    return []


def public_album_entries(services: AppServices) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    used: dict[str, int] = {}
    for rooted_path in sorted(services.auth.public_albums, key=str.lower):
        try:
            root_id, rel = parse_rooted_path(rooted_path)
        except Exception:
            continue
        root = services.roots.get(root_id)
        if root is None:
            continue
        name = rel.rstrip("/").split("/")[-1] if rel else (root.name or root_id)
        used[name] = used.get(name, 0) + 1
        display = name if used[name] == 1 else f"{name} ({root_id})"
        entries.append({"id": rooted_path, "name": display, "path": str((root / rel).resolve())})
    return entries


def is_public_path(services: AppServices, rooted_path: str) -> bool:
    normalized = normalize_rooted_path(rooted_path)
    if not normalized:
        return False
    for album in services.auth.public_albums:
        public_root = normalize_rooted_path(album)
        if normalized == public_root or normalized.startswith(f"{public_root}/"):
            return True
    return False


def is_public_or_ancestor(services: AppServices, rooted_path: str) -> bool:
    normalized = normalize_rooted_path(rooted_path)
    for album in services.auth.public_albums:
        public_root = normalize_rooted_path(album)
        if (
            normalized == public_root
            or normalized.startswith(f"{public_root}/")
            or public_root.startswith(f"{normalized}/")
        ):
            return True
    return False


def normalize_rooted_path(value: str) -> str:
    if not value:
        return ""
    return normalize_rel_path(value.strip().strip("/"))


def join_rooted(root_id: str, rel: str = "") -> str:
    rel = normalize_rel_path(rel)
    return root_id if not rel else f"{root_id}/{rel}"


def auth_status_payload(services: AppServices) -> dict:
    return {
        "enabled": auth_enabled(services),
        "role": current_role(services) or "none",
        "hasPassword": bool(services.auth.password),
        "publicAlbums": sorted(services.auth.public_albums),
        "loginBackgrounds": list(services.auth.login_backgrounds),
        "loginBackgroundUrls": [background_url(item) for item in services.auth.login_backgrounds],
        "loginBackgroundMode": services.auth.login_background_mode,
        "loginBackgroundFolder": services.auth.login_background_folder,
        "loginBackgroundLayout": services.auth.login_background_layout,
    }


def background_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} or value.startswith("/"):
        return value
    return f"/api/auth/background/{quote_path(normalize_rooted_path(value))}"


def login_background_gallery(services: AppServices, limit: int = 36) -> dict:
    provider = services.login_background_provider
    if provider is None or not login_background_plugin_enabled(services):
        return {"mode": "none", "photos": []}
    return provider.gallery(limit=limit)


def login_background_plugin_enabled(services: AppServices) -> bool:
    return "login_photo_wall" in services.enabled_plugins


def clear_login_background_cache(services: AppServices) -> None:
    provider = services.login_background_provider
    if provider is not None:
        provider.clear()


def ensure_login_background_cache(
    services: AppServices,
    limit: int = 36,
    force: bool = False,
    async_rebuild: bool = False,
) -> None:
    provider = services.login_background_provider
    if provider is None or not login_background_plugin_enabled(services):
        return
    provider.ensure(limit=limit, force=force, async_rebuild=async_rebuild)


def login_background_candidate_paths(services: AppServices) -> list[str]:
    provider = services.login_background_provider
    if provider is None or not login_background_plugin_enabled(services):
        return []
    return provider.candidate_paths()
