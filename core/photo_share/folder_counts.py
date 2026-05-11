from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock

from .constants import MEDIA_EXTENSIONS, PHOTO_EXTENSIONS, RATINGS_FILE, THUMBNAIL_DIR, VIDEO_EXTENSIONS
from .paths import to_relative


class FolderCountIndex:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.lock = Lock()
        self.counts: dict[str, int] = {}
        self.ready = False
        self.inflight = False
        self.refreshing: set[str] = set()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="folder-counts")
        self.scanned_entries = 0

    def ensure_async(self) -> bool:
        with self.lock:
            if self.ready or self.inflight:
                return False
            self.inflight = True
        self.executor.submit(self._rebuild_with_cleanup)
        return True

    def refresh_subtree_async(self, folder_path: Path) -> bool:
        rel = self._folder_key(folder_path)
        with self.lock:
            if rel in self.refreshing:
                return False
            self.refreshing.add(rel)
        self.executor.submit(self._refresh_subtree_with_cleanup, folder_path, rel)
        return True

    def get(self, folder_path: Path) -> int | None:
        rel = self._folder_key(folder_path)
        with self.lock:
            return self.counts.get(rel)

    def is_pending(self, folder_path: Path) -> bool:
        rel = self._folder_key(folder_path)
        with self.lock:
            return rel in self.refreshing or (self.inflight and rel not in self.counts) or rel not in self.counts

    def is_ready(self) -> bool:
        with self.lock:
            return self.ready

    def decrement_deleted_media(self, media_path: Path, amount: int = 1) -> None:
        if amount <= 0:
            return
        parent = media_path.parent
        with self.lock:
            if not self.ready:
                return
            for rel in self._ancestor_keys(parent):
                self.counts[rel] = max(0, self.counts.get(rel, 0) - amount)

    def _rebuild_with_cleanup(self) -> None:
        try:
            counts: dict[str, int] = {}
            self._scan_folder(self.root, counts)
            with self.lock:
                self.counts = counts
                self.ready = True
        except Exception as exc:
            print(f"Failed to build folder counts for {self.root}: {exc}")
        finally:
            with self.lock:
                self.inflight = False

    def _refresh_subtree_with_cleanup(self, folder_path: Path, rel: str) -> None:
        try:
            if not folder_path.exists() or not folder_path.is_dir():
                return
            subtree_counts: dict[str, int] = {}
            self._scan_folder(folder_path, subtree_counts)
            new_count = subtree_counts.get(rel, 0)
            with self.lock:
                was_ready = self.ready
                old_count = self.counts.get(rel, 0)
                delta = new_count - old_count
                self.counts.update(subtree_counts)
                if was_ready and delta:
                    for ancestor in self._ancestor_keys(folder_path.parent):
                        self.counts[ancestor] = max(0, self.counts.get(ancestor, 0) + delta)
        except Exception as exc:
            print(f"Failed to refresh folder counts for {folder_path}: {exc}")
        finally:
            with self.lock:
                self.refreshing.discard(rel)

    def _scan_folder(self, folder_path: Path, counts: dict[str, int]) -> int:
        total = 0
        try:
            with os.scandir(folder_path) as items:
                children = list(items)
        except OSError:
            counts[self._folder_key(folder_path)] = 0
            return 0

        for child in children:
            self._yield_periodically()
            if child.name in {RATINGS_FILE, THUMBNAIL_DIR}:
                continue
            try:
                child_path = Path(child.path)
                if child.is_dir():
                    total += self._scan_folder(child_path, counts)
                elif child.is_file() and self._is_counted_media(child_path, children):
                    total += 1
            except OSError:
                continue

        counts[self._folder_key(folder_path)] = total
        return total

    def _is_counted_media(self, path: Path, siblings: list[os.DirEntry]) -> bool:
        suffix = path.suffix.lower()
        if suffix not in MEDIA_EXTENSIONS:
            return False
        if suffix in VIDEO_EXTENSIONS and self._has_photo_sibling(path, siblings):
            return False
        return True

    def _has_photo_sibling(self, path: Path, siblings: list[os.DirEntry]) -> bool:
        stem = path.stem.lower()
        for sibling in siblings:
            try:
                sibling_path = Path(sibling.path)
                if sibling.is_file() and sibling_path.stem.lower() == stem and sibling_path.suffix.lower() in PHOTO_EXTENSIONS:
                    return True
            except OSError:
                continue
        return False

    def _yield_periodically(self) -> None:
        self.scanned_entries += 1
        if self.scanned_entries % 200 == 0:
            time.sleep(0.01)

    def _folder_key(self, folder_path: Path) -> str:
        return to_relative(self.root, folder_path) if folder_path != self.root else ""

    def _ancestor_keys(self, folder_path: Path) -> list[str]:
        keys: list[str] = []
        current = folder_path
        while True:
            try:
                current.relative_to(self.root)
            except ValueError:
                break
            keys.append(self._folder_key(current))
            if current == self.root:
                break
            current = current.parent
        return keys
