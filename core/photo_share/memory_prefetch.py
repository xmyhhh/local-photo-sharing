from __future__ import annotations

import mimetypes
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .constants import PHOTO_EXTENSIONS


@dataclass
class MemoryPrefetchSettings:
    enabled: bool = False
    memory_limit_gb: int = 2
    window_before: int = 20
    window_after: int = 20

    @property
    def max_bytes(self) -> int:
        return self.memory_limit_gb * 1024 * 1024 * 1024


@dataclass
class PrefetchItem:
    data: bytes
    mimetype: str
    mtime: float
    size: int
    clients: set[str] = field(default_factory=set)


class MemoryPrefetchPool:
    def __init__(self, settings: MemoryPrefetchSettings) -> None:
        self.settings = settings
        self._items: OrderedDict[str, PrefetchItem] = OrderedDict()
        self._client_keys: dict[str, set[str]] = {}
        self._inflight: set[str] = set()
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="photo-prefetch")
        self._bytes = 0

    def configure(self, settings: MemoryPrefetchSettings) -> None:
        with self._lock:
            self.settings = settings
            if not settings.enabled:
                self._clear_locked()
                return
            self._trim_locked()

    def get(self, path: Path) -> PrefetchItem | None:
        if not self.settings.enabled:
            return None
        key = self._key(path)
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            try:
                stat = path.stat()
            except OSError:
                self._remove_locked(key)
                return None
            if item.mtime != stat.st_mtime or item.size != stat.st_size:
                self._remove_locked(key)
                return None
            self._items.move_to_end(key)
            return item

    def prefetch(self, client_id: str, paths: list[Path]) -> None:
        if not client_id:
            return
        with self._lock:
            self.release(client_id)
            if not self.settings.enabled:
                return
            keys: set[str] = set()
            for path in paths:
                if path.suffix.lower() not in PHOTO_EXTENSIONS:
                    continue
                key = self._key(path)
                keys.add(key)
                item = self._items.get(key)
                if item is not None:
                    item.clients.add(client_id)
                    self._items.move_to_end(key)
                    continue
                if key in self._inflight:
                    continue
                self._inflight.add(key)
                self._executor.submit(self._load_path, client_id, key, path)
            self._client_keys[client_id] = keys
            self._trim_locked()

    def release(self, client_id: str) -> None:
        with self._lock:
            keys = self._client_keys.pop(client_id, set())
            for key in keys:
                item = self._items.get(key)
                if item is not None:
                    item.clients.discard(client_id)
            self._drop_unleased_locked()
            self._trim_locked()

    def clear(self) -> None:
        with self._lock:
            self._clear_locked()

    def _load_path(self, client_id: str, key: str, path: Path) -> None:
        try:
            stat = path.stat()
            if stat.st_size <= 0 or stat.st_size > self.settings.max_bytes:
                return
            data = path.read_bytes()
            mimetype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        except OSError:
            return
        finally:
            with self._lock:
                self._inflight.discard(key)

        with self._lock:
            if not self.settings.enabled:
                return
            if client_id not in self._client_keys or key not in self._client_keys[client_id]:
                return
            existing = self._items.get(key)
            if existing is not None:
                self._bytes -= len(existing.data)
            clients = set(existing.clients) if existing else set()
            clients.add(client_id)
            self._items[key] = PrefetchItem(
                data=data,
                mimetype=mimetype,
                mtime=stat.st_mtime,
                size=stat.st_size,
                clients=clients,
            )
            self._items.move_to_end(key)
            self._bytes += len(data)
            self._trim_locked()

    def _trim_locked(self) -> None:
        while self._bytes > self.settings.max_bytes and self._items:
            victim_key = next((key for key, item in self._items.items() if not item.clients), None)
            if victim_key is None:
                victim_key = next(iter(self._items))
            self._remove_locked(victim_key)

    def _drop_unleased_locked(self) -> None:
        for key in list(self._items.keys()):
            if not self._items[key].clients:
                self._remove_locked(key)

    def _remove_locked(self, key: str) -> None:
        item = self._items.pop(key, None)
        if item is not None:
            self._bytes -= len(item.data)

    def _clear_locked(self) -> None:
        self._items.clear()
        self._client_keys.clear()
        self._inflight.clear()
        self._bytes = 0

    @staticmethod
    def _key(path: Path) -> str:
        return str(path.resolve()).lower()
