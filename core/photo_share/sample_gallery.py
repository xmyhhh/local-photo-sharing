from __future__ import annotations

import shutil
from pathlib import Path

from .config import write_config
from .context import AppServices
from .paths import join_rooted_path, to_relative

SAMPLE_ALBUM_FOLDER = "Sample Gallery/Bing"
SAMPLE_MARKER_FILE = ".photo_share_sample_gallery_installed"
SAMPLE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}


def install_sample_gallery_if_available(services: AppServices, sample_root: Path) -> None:
    if not sample_root.is_dir():
        return
    source = sample_root / "bing"
    if not source.is_dir():
        return
    images = sorted(
        path
        for path in source.iterdir()
        if path.is_file() and path.suffix.lower() in SAMPLE_EXTENSIONS
    )
    if not images:
        return

    destination = (services.default_save_folder / SAMPLE_ALBUM_FOLDER).resolve()
    marker = destination / SAMPLE_MARKER_FILE
    installed_now = False
    if not marker.exists():
        destination.mkdir(parents=True, exist_ok=True)
        for image in images:
            target = destination / image.name
            if not target.exists():
                shutil.copy2(image, target)
        marker.write_text("installed\n", encoding="utf-8")
        installed_now = True

    rel = to_relative(services.roots[services.default_save_root_id].resolve(), destination)
    rooted = join_rooted_path(services.default_save_root_id, rel)
    if rooted not in services.auth.public_albums:
        services.auth.public_albums.add(rooted)
        auth = services.config.setdefault("auth", {})
        if isinstance(auth, dict):
            auth["public_albums"] = sorted(services.auth.public_albums)
            write_config(services.config_path, services.config)

    if installed_now:
        services.root_services[services.default_save_root_id].folder_counts.refresh_subtree_async(destination)
