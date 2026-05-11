from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from os import stat_result
from threading import Lock

from .constants import METADATA_WORKERS
from .ratings import read_embedded_rating
from .paths import to_relative
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
            if 0 <= rating <= 5:
                clean[str(key)] = rating
        return clean

    def _save(self) -> None:
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def get(self, rel_path: str) -> int:
        return self.data.get(rel_path, 0)

    def get_override(self, rel_path: str) -> int | None:
        return self.data.get(rel_path)

    def set(self, rel_path: str, value: int) -> None:
        with self.lock:
            self.data[rel_path] = value
            self._save()

    def delete(self, rel_path: str) -> None:
        with self.lock:
            self.data.pop(rel_path, None)
            self._save()


class MetadataStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.lock = Lock()
        self.data: dict[str, dict[str, int]] = {}
        self.errors: dict[str, str] = {}
        self.executor = ThreadPoolExecutor(max_workers=METADATA_WORKERS, thread_name_prefix="metadata")
        self.inflight: set[str] = set()

    def get_rating_ready(self, photo_path: Path, stat: stat_result | None = None) -> int:
        rel = to_relative(self.root, photo_path)
        file_stat = stat or photo_path.stat()
        cached = self.data.get(rel)
        if cached and cached.get("mtime") == int(file_stat.st_mtime) and cached.get("size") == file_stat.st_size:
            return cached.get("rating", 0)
        return 0

    def is_ready(self, photo_path: Path, stat: stat_result | None = None) -> bool:
        rel = to_relative(self.root, photo_path)
        file_stat = stat or photo_path.stat()
        cached = self.data.get(rel)
        return bool(cached and cached.get("mtime") == int(file_stat.st_mtime) and cached.get("size") == file_stat.st_size)

    def get_error(self, photo_path: Path) -> str | None:
        return self.errors.get(self._task_key(photo_path))

    def ensure(self, photo_path: Path) -> bool:
        if self.is_ready(photo_path):
            return False
        task_key = self._task_key(photo_path)
        with self.lock:
            if task_key in self.inflight:
                return False
            self.inflight.add(task_key)
            self.errors.pop(task_key, None)
        self.executor.submit(self._read_with_cleanup, photo_path, task_key)
        return True

    def _read_with_cleanup(self, photo_path: Path, task_key: str) -> None:
        try:
            self._read(photo_path)
        except Exception as exc:
            print(f"Failed to read metadata for {photo_path}: {exc}")
            with self.lock:
                self.errors[task_key] = str(exc)
        finally:
            with self.lock:
                self.inflight.discard(task_key)

    def _read(self, photo_path: Path) -> None:
        if not photo_path.exists():
            return
        rel = to_relative(self.root, photo_path)
        stat = photo_path.stat()
        cached = self.data.get(rel)
        if cached and cached.get("mtime") == int(stat.st_mtime) and cached.get("size") == stat.st_size:
            return
        rating = read_embedded_rating(photo_path)
        self.set_ready(photo_path, rating)

    def set_ready(self, photo_path: Path, rating: int) -> None:
        if not photo_path.exists():
            return
        rel = to_relative(self.root, photo_path)
        stat = photo_path.stat()
        with self.lock:
            self.data[rel] = {
                "mtime": int(stat.st_mtime),
                "size": stat.st_size,
                "rating": rating,
            }

    def delete(self, photo_path: Path) -> None:
        rel = to_relative(self.root, photo_path)
        with self.lock:
            self.data.pop(rel, None)
            for key in list(self.errors):
                if key.startswith(f"{rel}:"):
                    self.errors.pop(key, None)

    def _task_key(self, photo_path: Path) -> str:
        stat = photo_path.stat()
        rel = to_relative(self.root, photo_path)
        return f"{rel}:{int(stat.st_mtime)}:{stat.st_size}"



