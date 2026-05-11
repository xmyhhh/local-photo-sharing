from __future__ import annotations

import random
from io import BytesIO
from hmac import compare_digest
from pathlib import Path
from urllib.parse import urlparse

from flask import abort, session
from PIL import Image, ImageOps

from .context import AppServices
from .constants import PHOTO_EXTENSIONS
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
        if normalized == public_root or public_root.startswith(f"{normalized}/"):
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
    }


def background_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} or value.startswith("/"):
        return value
    return f"/api/auth/background/{quote_path(normalize_rooted_path(value))}"


def login_background_gallery(services: AppServices, limit: int = 36) -> dict:
    ensure_login_background_cache(services, limit=limit)
    return {"mode": services.auth.login_background_mode, "photos": services.login_background_items[:limit]}


def ensure_login_background_cache(services: AppServices, limit: int = 36) -> None:
    if services.auth.login_background_mode == "none":
        services.login_background_cache.clear()
        services.login_background_items = []
        return
    candidates = login_background_candidate_paths(services)
    random.shuffle(candidates)
    selected = candidates[: max(1, min(limit, 60))]
    next_cache: dict[str, bytes] = {}
    next_items: list[dict[str, str]] = []
    previous = services.login_background_cache
    for index, rooted in enumerate(selected):
        key = quote_path(rooted)
        data = previous.get(key) or build_login_background_jpeg(services, rooted)
        if data is None:
            continue
        next_cache[key] = data
        next_items.append({"path": rooted, "thumbUrl": f"/api/auth/background-memory/{key}", "key": key})
    services.login_background_cache.clear()
    services.login_background_cache.update(next_cache)
    services.login_background_items = next_items


def build_login_background_jpeg(services: AppServices, rooted: str) -> bytes | None:
    try:
        root_id, rel = parse_rooted_path(rooted)
        root_services = services.root_services[root_id]
        path = (root_services.root / rel).resolve()
        path.relative_to(root_services.root)
        if path.suffix.lower() not in PHOTO_EXTENSIONS:
            return None
        with Image.open(path) as image:
            output = ImageOps.exif_transpose(image)
            output.thumbnail((520, 520))
            if output.mode not in {"RGB", "L"}:
                output = output.convert("RGB")
            buffer = BytesIO()
            output.save(buffer, format="JPEG", quality=70, optimize=True)
            return buffer.getvalue()
    except Exception:
        return None


def login_background_candidate_paths(services: AppServices) -> list[str]:
    mode = services.auth.login_background_mode
    if mode == "rated":
        return rated_background_candidates(services)
    if mode == "folder":
        return folder_background_candidates(services)
    return []


def rated_background_candidates(services: AppServices) -> list[str]:
    candidates: list[str] = []
    for root_id, root_services in services.root_services.items():
        root_services.rating_index.ensure_async()
        for path in iter_limited_photos(root_services.root, 900):
            rel = normalize_rel_path(path.relative_to(root_services.root).as_posix())
            rating = root_services.ratings.get_override(rel)
            if rating is None:
                rating = root_services.rating_index.get(rel) or 0
            if rating > 0:
                candidates.append(join_rooted(root_id, rel))
    return candidates


def folder_background_candidates(services: AppServices) -> list[str]:
    folders = [services.auth.login_background_folder] if services.auth.login_background_folder else sorted(services.auth.public_albums)
    candidates: list[str] = []
    for item in folders:
        try:
            root_id, rel = parse_rooted_path(item)
        except Exception:
            continue
        root_services = services.root_services.get(root_id)
        if root_services is None:
            continue
        folder = (root_services.root / rel).resolve()
        try:
            folder.relative_to(root_services.root)
        except ValueError:
            continue
        if not folder.is_dir():
            continue
        candidates.extend(join_rooted(root_id, path.relative_to(root_services.root).as_posix()) for path in iter_limited_photos(folder, 900))
    return candidates


def iter_limited_photos(folder: Path, limit: int):
    seen = 0
    stack = [folder]
    while stack and seen < limit:
        current = stack.pop()
        try:
            children = list(current.iterdir())
        except OSError:
            continue
        random.shuffle(children)
        for child in children:
            if seen >= limit:
                break
            try:
                if child.is_dir():
                    stack.append(child)
                elif child.is_file() and child.suffix.lower() in PHOTO_EXTENSIONS:
                    seen += 1
                    yield child
            except OSError:
                continue
