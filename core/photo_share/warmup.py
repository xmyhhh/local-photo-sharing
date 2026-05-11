from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock, Thread
from time import monotonic
from typing import Any

from .constants import PHOTO_EXTENSIONS, THUMBNAIL_WORKERS
from .context import AppServices


@dataclass
class WarmupStatus:
    state: str = "idle"
    stage: str = ""
    total: int = 0
    completed: int = 0
    generated: int = 0
    failed: int = 0
    started_at: float | None = None
    finished_at: float | None = None
    error: str = ""
    _lock: Lock = field(default_factory=Lock, repr=False)

    def update(self, **values: Any) -> None:
        with self._lock:
            for key, value in values.items():
                setattr(self, key, value)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            elapsed = 0.0
            if self.started_at is not None:
                elapsed = (self.finished_at or monotonic()) - self.started_at
            progress = 1.0 if self.total <= 0 and self.state == "complete" else 0.0
            if self.total > 0:
                progress = min(1.0, max(0.0, self.completed / self.total))
            return {
                "state": self.state,
                "stage": self.stage,
                "total": self.total,
                "completed": self.completed,
                "generated": self.generated,
                "failed": self.failed,
                "progress": round(progress, 6),
                "elapsedSeconds": round(max(0.0, elapsed), 1),
                "error": self.error,
                "workers": THUMBNAIL_WORKERS,
            }


def start_warmup_thumbnail_caches(services: AppServices) -> WarmupStatus:
    status = WarmupStatus(state="scanning", stage="正在统计需要预热的缩略图", started_at=monotonic())
    services.warmup_status = status
    thread = Thread(
        target=warmup_thumbnail_caches,
        args=(services, status),
        name="thumbnail-warmup-main",
        daemon=True,
    )
    thread.start()
    return status


def warmup_thumbnail_caches(services: AppServices, status: WarmupStatus | None = None) -> None:
    own_status = status or WarmupStatus(state="scanning", stage="正在统计需要预热的缩略图", started_at=monotonic())
    services.warmup_status = own_status
    try:
        _warmup_thumbnail_caches(services, own_status)
    except Exception as exc:
        own_status.update(state="error", stage="缩略图预热失败", error=str(exc), finished_at=monotonic())
        raise


def _warmup_thumbnail_caches(services: AppServices, own_status: WarmupStatus) -> None:
    tasks: list[tuple[str, str, Path]] = []
    for root_id, root_services in services.root_services.items():
        for photo in iter_photos(root_services.root):
            for mode in root_services.thumbnails:
                tasks.append((root_id, mode, photo))

    total = len(tasks)
    if total == 0:
        own_status.update(state="complete", stage="没有找到需要预热的照片", total=0, completed=0, finished_at=monotonic())
        print("Warmup: no photos found.")
        return

    own_status.update(state="running", stage="正在生成缩略图缓存", total=total)
    print(f"Warmup: {total} thumbnail tasks, {THUMBNAIL_WORKERS} workers.")
    started = monotonic()
    generated = 0
    completed = 0
    failed = 0
    _print_progress(completed, total, generated, failed, started)

    with ThreadPoolExecutor(max_workers=THUMBNAIL_WORKERS, thread_name_prefix="thumbnail-warmup") as executor:
        futures = {
            executor.submit(_warmup_task, services, root_id, mode, photo): (root_id, mode, photo)
            for root_id, mode, photo in tasks
        }
        for future in as_completed(futures):
            completed += 1
            root_id, mode, photo = futures[future]
            try:
                if future.result():
                    generated += 1
            except Exception as exc:
                failed += 1
                print()
                print(f"Warmup failed: {root_id} {mode} {photo} ({exc})")
            own_status.update(completed=completed, generated=generated, failed=failed)
            if completed == total or completed % 20 == 0:
                _print_progress(completed, total, generated, failed, started)
                own_status.update(completed=completed, generated=generated, failed=failed)
    print()
    print("Warmup complete.")
    own_status.update(
        state="complete",
        stage="缩略图预热完成",
        completed=completed,
        generated=generated,
        failed=failed,
        finished_at=monotonic(),
    )


def _print_progress(completed: int, total: int, generated: int, failed: int, started: float) -> None:
    elapsed = max(0.1, monotonic() - started)
    percent = completed / total if total else 1
    bar_width = 34
    filled = min(bar_width, int(percent * bar_width))
    bar = "#" * filled + "-" * (bar_width - filled)
    print(
        f"\rWarmup [{bar}] {percent * 100:5.1f}% "
        f"{completed}/{total} generated {generated} failed {failed} "
        f"{completed / elapsed:.1f}/s",
        end="",
        flush=True,
    )


def iter_photos(root: Path):
    stack = [root]
    while stack:
        folder = stack.pop()
        try:
            children = list(folder.iterdir())
        except OSError:
            continue
        for child in children:
            try:
                if child.is_dir():
                    stack.append(child)
                elif child.is_file() and child.suffix.lower() in PHOTO_EXTENSIONS:
                    yield child
            except OSError:
                continue


def _warmup_task(services: AppServices, root_id: str, mode: str, photo: Path) -> bool:
    return services.root_services[root_id].thumbnails[mode].warmup_one(photo)
