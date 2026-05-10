from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from time import monotonic

from .constants import PHOTO_EXTENSIONS, THUMBNAIL_WORKERS
from .context import AppServices


def warmup_thumbnail_caches(services: AppServices) -> None:
    tasks: list[tuple[str, str, Path]] = []
    for root_id, root_services in services.root_services.items():
        for photo in iter_photos(root_services.root):
            for mode in root_services.thumbnails:
                tasks.append((root_id, mode, photo))

    total = len(tasks)
    if total == 0:
        print("Warmup: no photos found.")
        return

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
            if completed == total or completed % 20 == 0:
                _print_progress(completed, total, generated, failed, started)
    print()
    print("Warmup complete.")


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
