from __future__ import annotations

from pathlib import Path
from threading import Condition, Lock, Thread, get_ident
from time import monotonic, monotonic_ns

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
        self.condition = Condition(self.lock)
        self.queue: list[tuple[Path, str, str]] = []
        self.queued: set[str] = set()
        self.inflight: dict[str, float] = {}
        self.errors: dict[str, str] = {}
        for index in range(THUMBNAIL_WORKERS):
            Thread(target=self._worker_loop, name=f"{thread_name}_{index}", daemon=True).start()

    def get_ready(self, photo_path: Path, *, validate: bool = False) -> Path | None:
        rel = to_relative(self.root, photo_path)
        cache_path = self.cache_path_for_rel(rel)
        source_stat = photo_path.stat()

        if (
            cache_path.exists()
            and cache_path.stat().st_mtime >= source_stat.st_mtime
            and cache_path.stat().st_size > 0
        ):
            if validate and not self._is_valid_cache_file(cache_path):
                self._delete_cache_path(cache_path)
                return None
            return cache_path
        return None

    def ensure(self, photo_path: Path) -> bool:
        rel = to_relative(self.root, photo_path)
        task_key = self._task_key(photo_path)
        with self.lock:
            self._expire_stale_inflight()
            if task_key in self.inflight or task_key in self.queued:
                return False
            self.errors.pop(self._error_key(photo_path), None)
            self.queue.insert(0, (photo_path, rel, task_key))
            self.queued.add(task_key)
            while len(self.queue) > self.queue_limit:
                _, _, dropped_key = self.queue.pop()
                self.queued.discard(dropped_key)
            self.condition.notify()
        return True

    def warmup_one(self, photo_path: Path) -> bool:
        rel = to_relative(self.root, photo_path)
        before = self.get_ready(photo_path, validate=True)
        self._generate(photo_path, rel)
        return before is None and self.get_ready(photo_path, validate=True) is not None

    def needs_warmup(self, photo_path: Path, rel: str | None = None) -> bool:
        if rel is None:
            rel = to_relative(self.root, photo_path)
        try:
            source_stat = photo_path.stat()
        except OSError:
            return False
        cache_path = self.cache_path_for_rel(rel)
        if not cache_path.exists():
            return True
        try:
            cache_stat = cache_path.stat()
        except OSError:
            return True
        if cache_stat.st_mtime < source_stat.st_mtime or cache_stat.st_size <= 0:
            return True
        if not self._is_valid_cache_file(cache_path):
            self._delete_cache_path(cache_path)
            return True
        return False

    def warmup_from_prepared_image(self, photo_path: Path, rel: str, image: Image.Image) -> bool:
        if not self.needs_warmup(photo_path, rel):
            return False
        self._generate_from_prepared_image(photo_path, rel, image)
        return self.get_ready(photo_path, validate=True) is not None

    def cleanup_stale_temporary_files(self) -> int:
        if not self.cache_root.is_dir():
            return 0
        removed = 0
        tmp_paths = set(self.cache_root.glob("*.tmp.jpg")) | set(self.cache_root.glob(".*.tmp.jpg"))
        for tmp_path in tmp_paths:
            try:
                tmp_path.unlink()
                removed += 1
            except OSError:
                pass
        return removed

    def _worker_loop(self) -> None:
        while True:
            task = self._next_task()
            photo_path, rel, task_key = task
            self._generate_with_cleanup(photo_path, rel, task_key)

    def _next_task(self) -> tuple[Path, str, str]:
        with self.condition:
            while True:
                while self.queue:
                    photo_path, rel, task_key = self.queue.pop(0)
                    self.queued.discard(task_key)
                    if task_key in self.inflight:
                        continue
                    self.inflight[task_key] = monotonic()
                    return photo_path, rel, task_key
                self.condition.wait()

    def _generate_with_cleanup(self, photo_path: Path, rel: str, task_key: str) -> None:
        try:
            self._generate(photo_path, rel)
        except Exception as exc:
            print(f"Failed to generate cache for {photo_path}: {exc}")
            with self.lock:
                self.errors[self._error_key(photo_path)] = str(exc)
        finally:
            with self.lock:
                self.inflight.pop(task_key, None)

    def _generate(self, photo_path: Path, rel: str) -> None:
        if not photo_path.exists():
            return
        if not self.needs_warmup(photo_path, rel):
            return

        with Image.open(photo_path) as image:
            prepared = ImageOps.exif_transpose(image)
            self._generate_from_prepared_image(photo_path, rel, prepared)

    def _generate_from_prepared_image(self, photo_path: Path, rel: str, image: Image.Image) -> None:
        cache_path = self.cache_path_for_rel(rel)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = cache_path.with_name(f".{cache_path.stem}.{get_ident()}.{monotonic_ns()}.tmp.jpg")
        try:
            output = image.copy()
            output.thumbnail((self.size, self.size))
            if output.mode not in {"RGB", "L"}:
                output = output.convert("RGB")
            output.save(tmp_path, format="JPEG", quality=self.quality, optimize=True, progressive=False)
            tmp_path.replace(cache_path)
        finally:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass

    def delete(self, photo_path: Path) -> None:
        rel = to_relative(self.root, photo_path)
        self._delete_cache_path(self.cache_path_for_rel(rel))

    def get_error(self, photo_path: Path) -> str | None:
        with self.lock:
            return self.errors.get(self._error_key(photo_path))

    def _task_key(self, photo_path: Path) -> str:
        stat = photo_path.stat()
        rel = to_relative(self.root, photo_path)
        return f"{rel}:{int(stat.st_mtime)}:{stat.st_size}"

    def _error_key(self, photo_path: Path) -> str:
        return to_relative(self.root, photo_path)

    def _expire_stale_inflight(self) -> None:
        now = monotonic()
        stale = [task_key for task_key, started_at in self.inflight.items() if now - started_at > 90]
        for task_key in stale:
            self.inflight.pop(task_key, None)

    def cache_path_for_rel(self, rel: str) -> Path:
        return self.cache_root / f"{hash_text(rel)}.jpg"

    def _delete_cache_path(self, cache_path: Path) -> None:
        try:
            cache_path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass

    def _is_valid_cache_file(self, cache_path: Path) -> bool:
        try:
            with Image.open(cache_path) as image:
                image.verify()
            return True
        except Exception:
            return False




