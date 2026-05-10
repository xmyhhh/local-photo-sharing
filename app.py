from __future__ import annotations

import argparse
import json
import mimetypes
import os
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


def create_app(photo_root: Path) -> Flask:
    root = photo_root.resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Photo root does not exist or is not a folder: {root}")

    app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")
    ratings = RatingStore(root / RATINGS_FILE)
    thumbnails = ThumbnailStore(root, root / THUMBNAIL_DIR)

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
        entries: list[dict[str, Any]] = []

        for child in sorted(folder_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if child.name in {RATINGS_FILE, THUMBNAIL_DIR}:
                continue
            rel = to_relative(root, child)
            if child.is_dir():
                entries.append({"type": "folder", "name": child.name, "path": rel})
            elif child.suffix.lower() in JPG_EXTENSIONS:
                stat = child.stat()
                entries.append(
                    {
                        "type": "photo",
                        "name": child.name,
                        "path": rel,
                        "size": stat.st_size,
                        "mtime": int(stat.st_mtime),
                        "rating": ratings.get(rel),
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

    @app.get("/api/thumb/<path:photo_path>")
    def thumbnail(photo_path: str):
        path = resolve_photo(root, photo_path)
        thumb = thumbnails.get(path)
        return send_file(thumb, mimetype="image/jpeg")

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


class ThumbnailStore:
    def __init__(self, root: Path, thumb_root: Path) -> None:
        self.root = root
        self.thumb_root = thumb_root
        self.lock = Lock()

    def get(self, photo_path: Path) -> Path:
        rel = to_relative(self.root, photo_path)
        thumb_path = self.thumb_root / f"{rel.replace('/', '__')}.jpg"
        source_stat = photo_path.stat()

        with self.lock:
            if (
                thumb_path.exists()
                and thumb_path.stat().st_mtime >= source_stat.st_mtime
                and thumb_path.stat().st_size > 0
            ):
                return thumb_path

            thumb_path.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(photo_path) as image:
                image = ImageOps.exif_transpose(image)
                image.thumbnail((420, 420))
                if image.mode not in {"RGB", "L"}:
                    image = image.convert("RGB")
                image.save(thumb_path, format="JPEG", quality=82, optimize=True)
            return thumb_path

    def delete(self, photo_path: Path) -> None:
        rel = to_relative(self.root, photo_path)
        thumb_path = self.thumb_root / f"{rel.replace('/', '__')}.jpg"
        try:
            thumb_path.unlink()
        except FileNotFoundError:
            pass


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Share a local JPG folder on your LAN.")
    parser.add_argument("folder", type=Path, help="Folder that contains JPG photos to share.")
    parser.add_argument("--host", default="0.0.0.0", help="Listen address. Default: 0.0.0.0")
    parser.add_argument("--port", default=8000, type=int, help="Listen port. Default: 8000")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    app = create_app(args.folder)
    print(f"Sharing: {args.folder.resolve()}")
    print(f"Open on this computer: http://127.0.0.1:{args.port}")
    print("Open on LAN devices: http://<this-computer-LAN-IP>:%s" % args.port)
    app.run(host=args.host, port=args.port, debug=False)
