from __future__ import annotations

from pathlib import Path

from .constants import LIVE_VIDEO_EXTENSIONS


def find_live_video(photo_path: Path) -> Path | None:
    return find_case_insensitive_sibling(photo_path, LIVE_VIDEO_EXTENSIONS)


def is_live_video_for_photo(video_path: Path, photo_path: Path) -> bool:
    return video_path.suffix.lower() in LIVE_VIDEO_EXTENSIONS and video_path.stem.lower() == photo_path.stem.lower()


def find_case_insensitive_sibling(path: Path, suffixes: set[str]) -> Path | None:
    direct_matches = [path.with_suffix(suffix) for suffix in suffixes]
    for candidate in direct_matches:
        if candidate.is_file():
            return candidate
    try:
        children = path.parent.iterdir()
    except OSError:
        return None
    stem = path.stem.lower()
    suffixes_lower = {suffix.lower() for suffix in suffixes}
    for child in children:
        if child.is_file() and child.stem.lower() == stem and child.suffix.lower() in suffixes_lower:
            return child
    return None
