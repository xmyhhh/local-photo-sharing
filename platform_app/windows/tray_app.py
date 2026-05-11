from __future__ import annotations

import logging
import threading
import webbrowser
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

from core.photo_share.config import get_config_path, parse_args
from core.photo_share.runtime import get_app_base_dir
from core.photo_share.server import ServerRuntime, create_server_runtime

APP_NAME = "Local Photo Sharing"


def configure_logging() -> Path:
    deploy_dir = get_app_base_dir() / ".deploy"
    deploy_dir.mkdir(parents=True, exist_ok=True)
    log_path = deploy_dir / "tray-app.log"
    logging.basicConfig(
        filename=log_path,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )
    return log_path


def create_tray_icon_image() -> Image.Image:
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((10, 18, 54, 46), radius=8, fill=(40, 88, 180, 255))
    draw.rounded_rectangle((18, 12, 30, 22), radius=4, fill=(40, 88, 180, 255))
    draw.ellipse((24, 24, 40, 40), fill=(255, 255, 255, 255))
    draw.ellipse((29, 29, 35, 35), fill=(40, 88, 180, 255))
    return image


def open_in_browser(runtime: ServerRuntime) -> None:
    webbrowser.open(runtime.local_url)


def print_startup_summary(runtime: ServerRuntime) -> None:
    print(f"Config: {runtime.config_path}")
    print("Sharing:")
    for folder in runtime.folders:
        print(f"  - {folder.resolve()}")
    print(f"Open on this computer: {runtime.local_url}")
    print(f"Open on LAN devices: http://<this-computer-LAN-IP>:{runtime.port}")


def main() -> None:
    log_path = configure_logging()
    args = parse_args()
    config_path = get_config_path(args.config)
    runtime = create_server_runtime(config_path)
    print_startup_summary(runtime)
    logging.info("Starting tray app with config %s", config_path)

    server_thread = threading.Thread(target=runtime.serve_forever, name="photo-share-server", daemon=True)
    server_thread.start()

    icon: pystray.Icon | None = None

    def handle_open(icon_ref: pystray.Icon, item: pystray.MenuItem) -> None:
        del icon_ref, item
        logging.info("Opening browser: %s", runtime.local_url)
        open_in_browser(runtime)

    def handle_exit(icon_ref: pystray.Icon, item: pystray.MenuItem) -> None:
        del item
        logging.info("Exit requested from tray icon")
        try:
            runtime.shutdown()
        finally:
            icon_ref.stop()

    def setup(icon_ref: pystray.Icon) -> None:
        logging.info("Tray icon ready; log file: %s", log_path)

    icon = pystray.Icon(
        "local-photo-sharing",
        create_tray_icon_image(),
        APP_NAME,
        menu=pystray.Menu(
            pystray.MenuItem("Open Web UI", handle_open, default=True),
            pystray.MenuItem("Exit", handle_exit),
        ),
    )
    icon.run(setup=setup)


if __name__ == "__main__":
    main()
