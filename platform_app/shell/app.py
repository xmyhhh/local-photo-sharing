from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.photo_share.config import (
    build_default_config,
    parse_args,
    get_config_path,
    write_config,
)
from core.photo_share.runtime import get_app_base_dir
from core.photo_share.server import create_server_runtime

DEFAULT_LIBRARY_DIRNAME = ".photo_share_library"


def default_photo_root() -> Path:
    return get_app_base_dir() / DEFAULT_LIBRARY_DIRNAME


def prompt_initial_photo_root() -> Path | None:
    default_root = default_photo_root()
    print("Config file was not found. Let's set up your photo library folder.")
    print(f"Default folder: {default_root}")
    entered = input(f"Photo library folder (press Enter to use default: {default_root}): ").strip()
    if not entered:
        return default_root
    return Path(entered).expanduser()


def ensure_shell_config_ready(config_path: Path) -> bool:
    if config_path.exists():
        return True
    selected = prompt_initial_photo_root()
    if selected is None:
        return False
    selected.mkdir(parents=True, exist_ok=True)
    write_config(config_path, build_default_config(selected))
    print(f"Created config: {config_path}")
    print(f"Photo library folder: {selected}")
    return True


def main() -> None:
    args = parse_args()
    config_path = get_config_path(args.config)
    if not ensure_shell_config_ready(config_path):
        return
    runtime = create_server_runtime(config_path, warmup=args.mode == "warmup")
    print(f"Config: {runtime.config_path}")
    print("Sharing:")
    for folder in runtime.folders:
        print(f"  - {folder.resolve()}")
    print(f"Open on this computer: {runtime.local_url}")
    print("Open on LAN devices: http://<this-computer-LAN-IP>:%s" % runtime.port)
    runtime.serve_forever()


if __name__ == "__main__":
    main()
