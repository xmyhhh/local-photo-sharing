from __future__ import annotations

import random
import json
from io import BytesIO
from hmac import compare_digest
from pathlib import Path
from threading import Thread
from urllib.parse import urlparse

from flask import abort, session
from PIL import Image, ImageOps

from .context import AppServices
from .constants import CACHE_DIR, PHOTO_EXTENSIONS
from .paths import hash_text, normalize_rel_path, parse_rooted_path, quote_path

ROLE_ADMIN = "admin"
ROLE_GUEST = "guest"
LOGIN_BACKGROUND_CACHE_DIR = CACHE_DIR / "login_backgrounds"
LOGIN_BACKGROUND_MANIFEST = LOGIN_BACKGROUND_CACHE_DIR / "manifest.json"


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
    }


def background_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} or value.startswith("/"):
        return value
    return f"/api/auth/background/{quote_path(normalize_rooted_path(value))}"


def login_background_gallery(services: AppServices, limit: int = 36) -> dict:
    ensure_login_background_cache(services, limit=limit, async_rebuild=True)
    return {"mode": services.auth.login_background_mode, "photos": services.login_background_items[:limit]}


def ensure_login_background_cache(
    services: AppServices,
    limit: int = 36,
    force: bool = False,
    async_rebuild: bool = False,
) -> None:
    if services.auth.login_background_mode == "none":
        with services.login_background_lock:
            services.login_background_cache.clear()
            services.login_background_items = []
            services.login_background_cache_key = ""
        return
    cache_key = login_background_config_key(services)
    with services.login_background_lock:
        if not force and services.login_background_cache_key == cache_key and services.login_background_items:
            return
    if not force and restore_login_background_cache(services, cache_key):
        return
    if async_rebuild:
        schedule_login_background_rebuild(services, cache_key, limit)
        return
    rebuild_login_background_cache(services, cache_key, limit)


def schedule_login_background_rebuild(services: AppServices, cache_key: str, limit: int = 36) -> None:
    with services.login_background_lock:
        if services.login_background_refreshing:
            return
        services.login_background_refreshing = True

    def run() -> None:
        try:
            rebuild_login_background_cache(services, cache_key, limit)
        finally:
            with services.login_background_lock:
                services.login_background_refreshing = False

    Thread(target=run, name="login-background-cache", daemon=True).start()


def rebuild_login_background_cache(services: AppServices, cache_key: str, limit: int = 36) -> None:
    candidates = login_background_candidate_paths(services)
    random.shuffle(candidates)
    selected = candidates[: max(1, min(limit, 60))]
    next_cache: dict[str, bytes] = {}
    next_items: list[dict[str, str]] = []
    manifest_items: list[dict[str, object]] = []
    LOGIN_BACKGROUND_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for rooted in selected:
        source = login_background_source_info(services, rooted)
        if source is None:
            continue
        key = hash_text(f"{rooted}:{source['mtime']}:{source['size']}")
        cache_path = LOGIN_BACKGROUND_CACHE_DIR / f"{key}.jpg"
        data = read_cache_file(cache_path)
        if data is None:
            data = build_login_background_jpeg(services, rooted)
            if data is None:
                continue
            write_cache_file(cache_path, data)
        url_key = quote_path(key)
        if data is None:
            continue
        item = {
            "path": rooted,
            "thumbUrl": f"/api/auth/background-memory/{url_key}",
            "key": url_key,
            "cacheKey": cache_key,
        }
        next_cache[url_key] = data
        next_items.append(item)
        manifest_items.append({**item, "file": cache_path.name, "mtime": source["mtime"], "size": source["size"]})
    with services.login_background_lock:
        services.login_background_cache.clear()
        services.login_background_cache.update(next_cache)
        services.login_background_items = next_items
        services.login_background_cache_key = cache_key if next_items else ""
    write_login_background_manifest({"cacheKey": cache_key, "items": manifest_items})


def restore_login_background_cache(services: AppServices, cache_key: str) -> bool:
    manifest = read_login_background_manifest()
    if manifest.get("cacheKey") != cache_key:
        return False
    next_cache: dict[str, bytes] = {}
    next_items: list[dict[str, str]] = []
    for item in manifest.get("items", []):
        if not isinstance(item, dict):
            continue
        rooted = str(item.get("path") or "")
        source = login_background_source_info(services, rooted)
        if source is None or int(item.get("mtime") or -1) != source["mtime"] or int(item.get("size") or -1) != source["size"]:
            return False
        key = str(item.get("key") or "")
        file_name = str(item.get("file") or "")
        if not key or not file_name:
            return False
        data = read_cache_file(LOGIN_BACKGROUND_CACHE_DIR / file_name)
        if data is None:
            return False
        next_cache[key] = data
        next_items.append({"path": rooted, "thumbUrl": str(item.get("thumbUrl") or f"/api/auth/background-memory/{key}"), "key": key, "cacheKey": cache_key})
    if not next_items:
        return False
    with services.login_background_lock:
        services.login_background_cache.clear()
        services.login_background_cache.update(next_cache)
        services.login_background_items = next_items
        services.login_background_cache_key = cache_key
    return True


def login_background_config_key(services: AppServices) -> str:
    parts = [
        services.auth.login_background_mode,
        services.auth.login_background_folder,
        *sorted(services.auth.public_albums),
    ]
    return hash_text("|".join(parts))


def login_background_source_info(services: AppServices, rooted: str) -> dict[str, int] | None:
    try:
        root_id, rel = parse_rooted_path(rooted)
        root_services = services.root_services[root_id]
        path = (root_services.root / rel).resolve()
        path.relative_to(root_services.root)
        stat = path.stat()
        if not path.is_file() or path.suffix.lower() not in PHOTO_EXTENSIONS:
            return None
        return {"mtime": int(stat.st_mtime), "size": int(stat.st_size)}
    except Exception:
        return None


def read_cache_file(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


def write_cache_file(path: Path, data: bytes) -> None:
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_bytes(data)
    tmp_path.replace(path)


def read_login_background_manifest() -> dict:
    try:
        data = json.loads(LOGIN_BACKGROUND_MANIFEST.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_login_background_manifest(data: dict) -> None:
    LOGIN_BACKGROUND_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = LOGIN_BACKGROUND_MANIFEST.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(LOGIN_BACKGROUND_MANIFEST)


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
        root_services.rating_index.ensure_folder_async(root_services.root)
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
