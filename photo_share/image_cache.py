from __future__ import annotations

from pathlib import Path
from threading import Lock, Thread

from PIL import Image, ImageOps

from .constants import THUMBNAIL_WORKERS
from .paths import hash_text, to_relative
class ImageCacheStore:
    def __init__(
        self,
        root: Path,
        cache_root: Path,
        size: int,
        quality: int,
        thread_name: str,
        queue_limit: int = 50,
    ) -> None:
        self.root = root
        self.cache_root = cache_root
        self.size = size
        self.quality = quality
        self.queue_limit = queue_limit
        self.lock = Lock()
        self.queue: list[tuple[Path, str, str]] = []
        self.queued: set[str] = set()
        self.inflight: set[str] = set()
        self.errors: dict[str, str] = {}
        for index in range(THUMBNAIL_WORKERS):
            Thread(target=self._worker_loop, name=f"{thread_name}_{index}", daemon=True).start()

    def get_ready(self, photo_path: Path) -> Path | None:
        rel = to_relative(self.root, photo_path)
        cache_path = self.cache_root / f"{hash_text(rel)}.jpg"
        source_stat = photo_path.stat()

        if (
            cache_path.exists()
            and cache_path.stat().st_mtime >= source_stat.st_mtime
            and cache_path.stat().st_size > 0
        ):
            return cache_path
        return None

    def ensure(self, photo_path: Path) -> bool:
        rel = to_relative(self.root, photo_path)
        task_key = self._task_key(photo_path)
        with self.lock:
            if task_key in self.inflight or task_key in self.queued:
                return False
            self.errors.pop(self._error_key(photo_path), None)
            self.queue.insert(0, (photo_path, rel, task_key))
            self.queued.add(task_key)
            while len(self.queue) > self.queue_limit:
                _, _, dropped_key = self.queue.pop()
                self.queued.discard(dropped_key)
        return True

    def _worker_loop(self) -> None:
        import time

        while True:
            task = self._next_task()
            if task is None:
                time.sleep(0.03)
                continue
            photo_path, rel, task_key = task
            self._generate_with_cleanup(photo_path, rel, task_key)

    def _next_task(self) -> tuple[Path, str, str] | None:
        with self.lock:
            while self.queue:
                photo_path, rel, task_key = self.queue.pop(0)
                self.queued.discard(task_key)
                if task_key in self.inflight:
                    continue
                self.inflight.add(task_key)
                return photo_path, rel, task_key
        return None

    def _generate_with_cleanup(self, photo_path: Path, rel: str, task_key: str) -> None:
        try:
            self._generate(photo_path, rel)
        except Exception as exc:
            print(f"Failed to generate cache for {photo_path}: {exc}")
            with self.lock:
                self.errors[self._error_key(photo_path)] = str(exc)
        finally:
            with self.lock:
                self.inflight.discard(task_key)

    def _generate(self, photo_path: Path, rel: str) -> None:
        if not photo_path.exists():
            return
        cache_path = self.cache_root / f"{hash_text(rel)}.jpg"
        source_stat = photo_path.stat()

        if (
            cache_path.exists()
            and cache_path.stat().st_mtime >= source_stat.st_mtime
            and cache_path.stat().st_size > 0
        ):
            return

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = cache_path.with_name(f"{cache_path.stem}.tmp.jpg")
        with Image.open(photo_path) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail((self.size, self.size))
            if image.mode not in {"RGB", "L"}:
                image = image.convert("RGB")
            image.save(tmp_path, format="JPEG", quality=self.quality, optimize=True, progressive=True)
        tmp_path.replace(cache_path)

    def delete(self, photo_path: Path) -> None:
        rel = to_relative(self.root, photo_path)
        cache_path = self.cache_root / f"{hash_text(rel)}.jpg"
        try:
            cache_path.unlink()
        except FileNotFoundError:
            pass

    def get_error(self, photo_path: Path) -> str | None:
        with self.lock:
            return self.errors.get(self._error_key(photo_path))

    def _task_key(self, photo_path: Path) -> str:
        stat = photo_path.stat()
        rel = to_relative(self.root, photo_path)
        return f"{rel}:{int(stat.st_mtime)}:{stat.st_size}"

    def _error_key(self, photo_path: Path) -> str:
        return to_relative(self.root, photo_path)




