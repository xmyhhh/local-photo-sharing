from __future__ import annotations

import mimetypes
import os
import threading
import gc
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .constants import PHOTO_EXTENSIONS


@dataclass
class MemoryPrefetchSettings:
    enabled: bool = False
    memory_limit_mb: int = 1024
    window_before: int = 5
    window_after: int = 35

    @property
    def max_bytes(self) -> int:
        return self.memory_limit_mb * 1024 * 1024


def system_prefetch_memory_limit_mb() -> int:
    try:
        if os.name == "nt":
            import ctypes

            class MemoryStatusEx(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MemoryStatusEx()
            status.dwLength = ctypes.sizeof(status)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            total_mb = status.ullTotalPhys // (1024 * 1024)
        else:
            pages = os.sysconf("SC_PHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            total_mb = pages * page_size // (1024 * 1024)
    except Exception:
        total_mb = 20480
    return max(256, int(total_mb) - 4096)


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
        # OrderedDict 既存数据，也承担 LRU 顺序；最近访问/更新的键会被移动到尾部。
        self._items: OrderedDict[str, PrefetchItem] = OrderedDict()
        # client_id -> 当前这位客户端希望保留的路径集合，相当于一层“租约”。
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
            # 命中即刷新 LRU，说明这张图最近真的被访问过。
            self._items.move_to_end(key)
            return item

    def prefetch(self, client_id: str, paths: list[Path]) -> None:
        if not client_id:
            return
        with self._lock:
            # 新一轮 prefetch 视为“完整替换”当前 client 的关注窗口，先撤销旧租约再挂新租约。
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
            removed = self._drop_unleased_locked()
            self._trim_locked()
            self._maybe_return_memory(removed)

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
                # 异步加载完成时，如果这个 client 已经翻页/退出，结果直接丢弃。
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
        removed = 0
        while self._bytes > self.settings.max_bytes and self._items:
            # 先淘汰没有任何 client 租约的旧项；如果全都还被租着，再从最老项开始顶掉。
            victim_key = next((key for key, item in self._items.items() if not item.clients), None)
            if victim_key is None:
                victim_key = next(iter(self._items))
            removed += self._remove_locked(victim_key)
        self._maybe_return_memory(removed)

    def _drop_unleased_locked(self) -> int:
        removed = 0
        for key in list(self._items.keys()):
            if not self._items[key].clients:
                removed += self._remove_locked(key)
        return removed

    def _remove_locked(self, key: str) -> int:
        item = self._items.pop(key, None)
        if item is not None:
            size = len(item.data)
            self._bytes -= size
            return size
        return 0

    def _clear_locked(self) -> None:
        removed = self._bytes
        self._items.clear()
        self._client_keys.clear()
        self._inflight.clear()
        self._bytes = 0
        self._maybe_return_memory(removed)

    @staticmethod
    def _key(path: Path) -> str:
        return str(path.resolve()).lower()

    @staticmethod
    def _maybe_return_memory(removed_bytes: int) -> None:
        if removed_bytes <= 0:
            return
        # Python 对象删掉后，进程 RSS 不一定立刻下降；这里主动推动一次回收。
        gc.collect()
        if os.name == "nt":
            return
        try:
            import ctypes

            libc = ctypes.CDLL(None)
            malloc_trim = getattr(libc, "malloc_trim", None)
            if malloc_trim is not None:
                # glibc 下尝试把空闲堆页归还给系统，Linux 上更容易看到 RSS 回落。
                malloc_trim(0)
        except Exception:
            return
