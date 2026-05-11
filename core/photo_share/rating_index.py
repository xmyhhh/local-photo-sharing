from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Condition, Lock
from time import perf_counter

from .constants import PHOTO_EXTENSIONS, METADATA_WORKERS
from .paths import to_relative
from .ratings import read_embedded_rating, read_xmp_head_rating
from .stores import MetadataStore, RatingStore
class RatingIndex:
    def __init__(self, root: Path, ratings: RatingStore, metadata: MetadataStore) -> None:
        self.root = root
        self.ratings = ratings
        self.metadata = metadata
        self.lock = Lock()
        self.condition = Condition(self.lock)
        self.by_path: dict[str, dict[str, int]] = {}
        self.by_rating: dict[int, set[str]] = {rating: set() for rating in range(0, 6)}
        self.indexed_folders: dict[str, int] = {}
        self.folder_inflight: set[str] = set()
        self.executor = ThreadPoolExecutor(max_workers=METADATA_WORKERS, thread_name_prefix="rating-index")
        self.folder_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rating-index-folder")

    def ensure_folder(self, folder_path: Path) -> None:
        folder_key = to_relative(self.root, folder_path) if folder_path != self.root else ""
        newest = self._folder_signature(folder_path)
        with self.lock:
            if self.indexed_folders.get(folder_key) == newest:
                return

        try:
            photos = [child for child in folder_path.iterdir() if child.suffix.lower() in PHOTO_EXTENSIONS and child.is_file()]
            list(self.executor.map(self.ensure_photo_quick, photos))
            with self.lock:
                self.indexed_folders[folder_key] = newest
        finally:
            with self.condition:
                self.folder_inflight.discard(folder_key)
                self.condition.notify_all()

    def ensure_folder_async(self, folder_path: Path) -> bool:
        folder_key = to_relative(self.root, folder_path) if folder_path != self.root else ""
        newest = self._folder_signature(folder_path)
        with self.lock:
            if self.indexed_folders.get(folder_key) == newest or folder_key in self.folder_inflight:
                return False
            self.folder_inflight.add(folder_key)
        self.folder_executor.submit(self.ensure_folder, folder_path)
        return True

    def index_folder_budget(self, folder_path: Path, budget: float) -> None:
        folder_key = to_relative(self.root, folder_path) if folder_path != self.root else ""
        newest = self._folder_signature(folder_path)
        with self.lock:
            if self.indexed_folders.get(folder_key) == newest:
                return
        deadline = perf_counter() + budget
        complete = True
        for child in sorted(folder_path.iterdir(), key=lambda p: p.name.lower()):
            if child.suffix.lower() not in PHOTO_EXTENSIONS or not child.is_file():
                continue
            if perf_counter() >= deadline:
                complete = False
                break
            self.ensure_photo_quick(child)
        if complete:
            with self.condition:
                self.indexed_folders[folder_key] = newest
                self.condition.notify_all()

    def is_folder_ready(self, folder_path: Path) -> bool:
        folder_key = to_relative(self.root, folder_path) if folder_path != self.root else ""
        newest = self._folder_signature(folder_path)
        with self.lock:
            return self.indexed_folders.get(folder_key) == newest

    def wait_for_folder(self, folder_path: Path, timeout: float) -> bool:
        folder_key = to_relative(self.root, folder_path) if folder_path != self.root else ""
        newest = self._folder_signature(folder_path)
        deadline = perf_counter() + timeout
        with self.condition:
            while perf_counter() < deadline:
                if self.indexed_folders.get(folder_key) == newest:
                    return True
                remaining = max(0.0, deadline - perf_counter())
                self.condition.wait(timeout=remaining)
            return self.indexed_folders.get(folder_key) == newest

    def ensure_photo(self, photo_path: Path) -> int:
        rel = to_relative(self.root, photo_path)
        stat = photo_path.stat()
        cached = self.by_path.get(rel)
        if cached and cached.get("mtime") == int(stat.st_mtime) and cached.get("size") == stat.st_size:
            return cached.get("rating", 0)

        override = self.ratings.get_override(rel)
        rating = override if override is not None else read_embedded_rating(photo_path)
        self.set(rel, rating, photo_path)
        self.metadata.set_ready(photo_path, rating)
        return rating

    def ensure_photo_quick(self, photo_path: Path) -> int:
        rel = to_relative(self.root, photo_path)
        stat = photo_path.stat()
        cached = self.by_path.get(rel)
        if cached and cached.get("mtime") == int(stat.st_mtime) and cached.get("size") == stat.st_size:
            return cached.get("rating", 0)

        override = self.ratings.get_override(rel)
        rating = override if override is not None else read_xmp_head_rating(photo_path)
        self.set(rel, rating, photo_path)
        if rating:
            self.metadata.set_ready(photo_path, rating)
        return rating

    def get(self, rel: str) -> int | None:
        cached = self.by_path.get(rel)
        if not cached:
            return None
        return cached.get("rating", 0)

    def set(self, rel: str, rating: int, photo_path: Path | None = None) -> None:
        if photo_path is None:
            photo_path = self.root / rel
        stat = photo_path.stat()
        with self.lock:
            old = self.by_path.get(rel)
            if old:
                self.by_rating.get(old.get("rating", 0), set()).discard(rel)
            self.by_path[rel] = {
                "mtime": int(stat.st_mtime),
                "size": stat.st_size,
                "rating": rating,
            }
            self.by_rating.setdefault(rating, set()).add(rel)

    def delete(self, rel: str) -> None:
        with self.lock:
            old = self.by_path.pop(rel, None)
            if old:
                self.by_rating.get(old.get("rating", 0), set()).discard(rel)

    def _folder_signature(self, folder_path: Path) -> int:
        newest = 0
        for child in folder_path.iterdir():
            if child.suffix.lower() in PHOTO_EXTENSIONS and child.is_file():
                newest = max(newest, int(child.stat().st_mtime))
        return newest



