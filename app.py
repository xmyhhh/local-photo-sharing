from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from typing import Any

from flask import Flask, abort, jsonify, request, send_file
from PIL import Image, ImageOps

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
JPG_EXTENSIONS = {".jpg", ".jpeg"}
RATINGS_FILE = ".photo_share_ratings.json"
THUMBNAIL_DIR = ".photo_share_thumbs"
CACHE_DIR = APP_DIR / ".photo_share_cache"
THUMBNAIL_WORKERS = max(1, os.cpu_count() or 1)
DEFAULT_CONFIG_FILE = APP_DIR / "config.json"
DEFAULT_CONFIG = {
    "photo_folder": "D:/your/photo/folder",
    "host": "0.0.0.0",
    "port": 8000,
}


def create_app(photo_root: Path) -> Flask:
    root = photo_root.resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Photo root does not exist or is not a folder: {root}")

    app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")
    ratings = RatingStore(root / RATINGS_FILE)
    cache_root = CACHE_DIR / root_cache_key(root)
    metadata = MetadataStore(root, cache_root / "metadata.json")
    thumbnails = ThumbnailStore(root, cache_root / "thumbs")

    @app.get("/")
    def index():
        return send_file(STATIC_DIR / "index.html")

    @app.get("/api/config")
    def config():
        return jsonify({"root": str(root), "allowDelete": True})

    @app.get("/api/photos")
    def photos():
        folder = request.args.get("folder", "")
        folder_path = resolve_folder(root, folder)
        filters = PhotoFilters.from_request(request.args)
        entries: list[dict[str, Any]] = []

        for child in sorted(folder_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if child.name in {RATINGS_FILE, THUMBNAIL_DIR}:
                continue
            rel = to_relative(root, child)
            if child.is_dir():
                entries.append({"type": "folder", "name": child.name, "path": rel})
            elif child.suffix.lower() in JPG_EXTENSIONS:
                stat = child.stat()
                rating = ratings.get(rel)
                if rating == 0:
                    rating = metadata.get_rating(child)
                if not filters.matches_photo(rating, int(stat.st_mtime)):
                    continue
                entries.append(
                    {
                        "type": "photo",
                        "name": child.name,
                        "path": rel,
                        "size": stat.st_size,
                        "mtime": int(stat.st_mtime),
                        "rating": rating,
                    }
                )

        parent = ""
        if folder:
            parent_path = Path(folder).parent
            parent = "" if str(parent_path) == "." else as_posix(parent_path)

        return jsonify({"folder": folder, "parent": parent, "entries": entries})

    @app.get("/api/image/<path:photo_path>")
    def image(photo_path: str):
        path = resolve_photo(root, photo_path)
        return send_file(path, mimetype=mimetypes.guess_type(path.name)[0] or "image/jpeg")

    @app.get("/api/download/<path:photo_path>")
    def download(photo_path: str):
        path = resolve_photo(root, photo_path)
        return send_file(
            path,
            mimetype=mimetypes.guess_type(path.name)[0] or "image/jpeg",
            as_attachment=True,
            download_name=path.name,
        )

    @app.get("/api/thumb/<path:photo_path>")
    def thumbnail(photo_path: str):
        path = resolve_photo(root, photo_path)
        thumb = thumbnails.get_ready(path)
        if thumb is None:
            thumbnails.ensure(path)
            return jsonify({"status": "processing"}), 202
        return send_file(thumb, mimetype="image/jpeg")

    @app.get("/api/thumb-status/<path:photo_path>")
    def thumbnail_status(photo_path: str):
        path = resolve_photo(root, photo_path)
        thumb = thumbnails.get_ready(path)
        if thumb is not None:
            return jsonify({"status": "ready"})
        queued = thumbnails.ensure(path)
        return jsonify({"status": "queued" if queued else "processing"}), 202

    @app.post("/api/rating/<path:photo_path>")
    def set_rating(photo_path: str):
        resolve_photo(root, photo_path)
        data = request.get_json(silent=True) or {}
        value = data.get("rating")
        if not isinstance(value, int) or value < 0 or value > 5:
            abort(400, "rating must be an integer from 0 to 5")

        rel = normalize_rel_path(photo_path)
        ratings.set(rel, value)
        return jsonify({"path": rel, "rating": ratings.get(rel)})

    @app.delete("/api/photo/<path:photo_path>")
    def delete_photo(photo_path: str):
        path = resolve_photo(root, photo_path)
        rel = to_relative(root, path)
        path.unlink()
        ratings.delete(rel)
        thumbnails.delete(path)
        metadata.delete(path)
        return jsonify({"deleted": rel})

    return app


class RatingStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = Lock()
        self.data: dict[str, int] = self._load()

    def _load(self) -> dict[str, int]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        clean: dict[str, int] = {}
        for key, value in raw.items():
            try:
                rating = int(value)
            except (TypeError, ValueError):
                continue
            if 1 <= rating <= 5:
                clean[str(key)] = rating
        return clean

    def _save(self) -> None:
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def get(self, rel_path: str) -> int:
        return self.data.get(rel_path, 0)

    def set(self, rel_path: str, value: int) -> None:
        with self.lock:
            if value == 0:
                self.data.pop(rel_path, None)
            else:
                self.data[rel_path] = value
            self._save()

    def delete(self, rel_path: str) -> None:
        with self.lock:
            self.data.pop(rel_path, None)
            self._save()


class MetadataStore:
    def __init__(self, root: Path, path: Path) -> None:
        self.root = root
        self.path = path
        self.lock = Lock()
        self.data: dict[str, dict[str, int]] = self._load()

    def _load(self) -> dict[str, dict[str, int]]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        clean: dict[str, dict[str, int]] = {}
        for key, value in raw.items():
            if not isinstance(value, dict):
                continue
            try:
                clean[str(key)] = {
                    "mtime": int(value.get("mtime", 0)),
                    "size": int(value.get("size", 0)),
                    "rating": int(value.get("rating", 0)),
                }
            except (TypeError, ValueError):
                continue
        return clean

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def get_rating(self, photo_path: Path) -> int:
        rel = to_relative(self.root, photo_path)
        stat = photo_path.stat()
        cached = self.data.get(rel)
        if cached and cached.get("mtime") == int(stat.st_mtime) and cached.get("size") == stat.st_size:
            return cached.get("rating", 0)

        rating = read_embedded_rating(photo_path)
        with self.lock:
            self.data[rel] = {
                "mtime": int(stat.st_mtime),
                "size": stat.st_size,
                "rating": rating,
            }
            self._save()
        return rating

    def delete(self, photo_path: Path) -> None:
        rel = to_relative(self.root, photo_path)
        with self.lock:
            self.data.pop(rel, None)
            self._save()


class ThumbnailStore:
    def __init__(self, root: Path, thumb_root: Path) -> None:
        self.root = root
        self.thumb_root = thumb_root
        self.lock = Lock()
        self.executor = ThreadPoolExecutor(max_workers=THUMBNAIL_WORKERS, thread_name_prefix="thumb")
        self.inflight: set[str] = set()

    def get_ready(self, photo_path: Path) -> Path | None:
        rel = to_relative(self.root, photo_path)
        thumb_path = self.thumb_root / f"{hash_text(rel)}.jpg"
        source_stat = photo_path.stat()

        if (
            thumb_path.exists()
            and thumb_path.stat().st_mtime >= source_stat.st_mtime
            and thumb_path.stat().st_size > 0
        ):
            return thumb_path
        return None

    def ensure(self, photo_path: Path) -> bool:
        rel = to_relative(self.root, photo_path)
        task_key = self._task_key(photo_path)
        with self.lock:
            if task_key in self.inflight:
                return False
            self.inflight.add(task_key)
        self.executor.submit(self._generate_with_cleanup, photo_path, rel, task_key)
        return True

    def _generate_with_cleanup(self, photo_path: Path, rel: str, task_key: str) -> None:
        try:
            self._generate(photo_path, rel)
        finally:
            with self.lock:
                self.inflight.discard(task_key)

    def _generate(self, photo_path: Path, rel: str) -> None:
        if not photo_path.exists():
            return
        thumb_path = self.thumb_root / f"{hash_text(rel)}.jpg"
        source_stat = photo_path.stat()

        if (
            thumb_path.exists()
            and thumb_path.stat().st_mtime >= source_stat.st_mtime
            and thumb_path.stat().st_size > 0
        ):
            return

        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = thumb_path.with_suffix(".tmp")
        with Image.open(photo_path) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail((360, 360))
            if image.mode not in {"RGB", "L"}:
                image = image.convert("RGB")
            image.save(tmp_path, format="JPEG", quality=72, optimize=True)
        tmp_path.replace(thumb_path)

    def delete(self, photo_path: Path) -> None:
        rel = to_relative(self.root, photo_path)
        thumb_path = self.thumb_root / f"{hash_text(rel)}.jpg"
        try:
            thumb_path.unlink()
        except FileNotFoundError:
            pass

    def _task_key(self, photo_path: Path) -> str:
        stat = photo_path.stat()
        rel = to_relative(self.root, photo_path)
        return f"{rel}:{int(stat.st_mtime)}:{stat.st_size}"


class PhotoFilters:
    def __init__(self, rating: int | None, date_from: int | None, date_to: int | None) -> None:
        self.rating = rating
        self.date_from = date_from
        self.date_to = date_to

    @classmethod
    def from_request(cls, args: Any) -> "PhotoFilters":
        rating = parse_optional_int(args.get("rating"), 0, 5)
        date_from = parse_date_start(args.get("date_from"))
        date_to = parse_date_end(args.get("date_to"))
        return cls(rating, date_from, date_to)

    def matches_photo(self, photo_rating: int, mtime: int) -> bool:
        if self.rating is not None and photo_rating != self.rating:
            return False
        if self.date_from is not None and mtime < self.date_from:
            return False
        if self.date_to is not None and mtime > self.date_to:
            return False
        return True


def resolve_folder(root: Path, rel_path: str) -> Path:
    path = resolve_inside(root, rel_path)
    if not path.is_dir():
        abort(404)
    return path


def resolve_photo(root: Path, rel_path: str) -> Path:
    path = resolve_inside(root, rel_path)
    if not path.is_file() or path.suffix.lower() not in JPG_EXTENSIONS:
        abort(404)
    return path


def resolve_inside(root: Path, rel_path: str) -> Path:
    normalized = normalize_rel_path(rel_path)
    path = (root / normalized).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        abort(403)
    return path


def normalize_rel_path(path: str) -> str:
    normalized = Path(path.replace("\\", "/"))
    if normalized.is_absolute() or ".." in normalized.parts:
        abort(403)
    result = as_posix(normalized)
    return "" if result == "." else result


def to_relative(root: Path, path: Path) -> str:
    return as_posix(path.resolve().relative_to(root))


def as_posix(path: Path) -> str:
    return path.as_posix()


def root_cache_key(root: Path) -> str:
    return hash_text(str(root).lower())


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def parse_optional_int(value: str | None, minimum: int, maximum: int) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except ValueError:
        abort(400, f"Expected integer from {minimum} to {maximum}.")
    if parsed < minimum or parsed > maximum:
        abort(400, f"Expected integer from {minimum} to {maximum}.")
    return parsed


def parse_date_start(value: str | None) -> int | None:
    if not value:
        return None
    from datetime import datetime

    try:
        return int(datetime.fromisoformat(value).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    except ValueError:
        abort(400, "date_from must use YYYY-MM-DD format.")


def parse_date_end(value: str | None) -> int | None:
    if not value:
        return None
    from datetime import datetime

    try:
        return int(datetime.fromisoformat(value).replace(hour=23, minute=59, second=59, microsecond=999999).timestamp())
    except ValueError:
        abort(400, "date_to must use YYYY-MM-DD format.")


def read_embedded_rating(photo_path: Path) -> int:
    rating = read_exif_rating(photo_path)
    if rating:
        return rating
    return read_xmp_rating(photo_path)


def read_exif_rating(photo_path: Path) -> int:
    try:
        with Image.open(photo_path) as image:
            exif = image.getexif()
    except Exception:
        return 0

    rating = normalize_rating_value(exif.get(18246))
    if rating:
        return rating

    percent = exif.get(18249)
    try:
        percent_int = int(percent)
    except (TypeError, ValueError):
        return 0
    return normalize_rating_percent(percent_int)


def read_xmp_rating(photo_path: Path) -> int:
    try:
        raw = photo_path.read_bytes()
    except OSError:
        return 0

    marker = b"xmp:Rating"
    index = raw.find(marker)
    if index < 0:
        return 0
    window = raw[index : index + 80].decode("utf-8", errors="ignore")

    for separator in ('="', "='", ">"):
        pos = window.find(separator)
        if pos < 0:
            continue
        tail = window[pos + len(separator) :]
        for char in tail:
            if char.isdigit():
                return normalize_rating_value(char)
            if char not in {" ", "\t", "\r", "\n"}:
                break
    return 0


def normalize_rating_value(value: Any) -> int:
    try:
        rating = int(value)
    except (TypeError, ValueError):
        return 0
    if rating < 1:
        return 0
    return min(rating, 5)


def normalize_rating_percent(value: int) -> int:
    if value <= 0:
        return 0
    if value <= 1:
        return 1
    if value <= 25:
        return 2
    if value <= 50:
        return 3
    if value <= 75:
        return 4
    return 5


def create_default_config(config_path: Path) -> None:
    config_path.write_text(
        json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_config(config_path: Path) -> dict[str, Any] | None:
    if not config_path.exists():
        create_default_config(config_path)
        print(f"Config file was not found. Created default config: {config_path}")
        print("Edit photo_folder in the config file, then start the app again.")
        return None

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON config: {config_path} ({exc})") from exc

    if not isinstance(config, dict):
        raise ValueError("Config root must be a JSON object.")
    return config


def get_config_path(value: str | None) -> Path:
    if not value:
        return DEFAULT_CONFIG_FILE
    return Path(value).expanduser().resolve()


def get_photo_folder(config: dict[str, Any]) -> Path:
    value = config.get("photo_folder")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Config field photo_folder must be a non-empty string.")
    return Path(value).expanduser()


def get_host(config: dict[str, Any]) -> str:
    value = config.get("host", DEFAULT_CONFIG["host"])
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Config field host must be a non-empty string.")
    return value


def get_port(config: dict[str, Any]) -> int:
    value = config.get("port", DEFAULT_CONFIG["port"])
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Config field port must be an integer.") from exc
    if port < 1 or port > 65535:
        raise ValueError("Config field port must be between 1 and 65535.")
    return port


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Share a local JPG folder on your LAN.")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_FILE),
        help="JSON config file path. Default: config.json next to app.py",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    config_path = get_config_path(args.config)
    config = load_config(config_path)
    if config is None:
        raise SystemExit(0)

    folder = get_photo_folder(config)
    host = get_host(config)
    port = get_port(config)
    app = create_app(folder)
    print(f"Config: {config_path}")
    print(f"Sharing: {folder.resolve()}")
    print(f"Open on this computer: http://127.0.0.1:{port}")
    print("Open on LAN devices: http://<this-computer-LAN-IP>:%s" % port)
    app.run(host=host, port=port, debug=False)
