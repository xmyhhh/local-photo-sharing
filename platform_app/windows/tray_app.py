from __future__ import annotations

import logging
import os
import threading
import webbrowser
from pathlib import Path
import sys
import winreg

import pystray
from PIL import Image, ImageDraw

from core.photo_share.config import get_config_path, parse_args
from core.photo_share.runtime import get_app_base_dir
from core.photo_share.server import ServerRuntime, create_server_runtime

APP_NAME = "Local Photo Sharing"
AUTOSTART_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_VALUE_NAME = "LocalPhotoSharingTray"


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


def get_autostart_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable)}"'
    return f'"{Path(sys.executable)}" "{Path(__file__).resolve()}"'


def is_autostart_enabled() -> bool:
    expected = get_autostart_command()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_REG_PATH, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, AUTOSTART_VALUE_NAME)
    except FileNotFoundError:
        return False
    return os.path.normcase(str(value)) == os.path.normcase(expected)


def set_autostart_enabled(enabled: bool) -> None:
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        AUTOSTART_REG_PATH,
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        if enabled:
            winreg.SetValueEx(key, AUTOSTART_VALUE_NAME, 0, winreg.REG_SZ, get_autostart_command())
            return
        try:
            winreg.DeleteValue(key, AUTOSTART_VALUE_NAME)
        except FileNotFoundError:
            pass


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

    def autostart_checked(item: pystray.MenuItem) -> bool:
        del item
        return is_autostart_enabled()

    def handle_toggle_autostart(icon_ref: pystray.Icon, item: pystray.MenuItem) -> None:
        del item
        enabled = not is_autostart_enabled()
        set_autostart_enabled(enabled)
        logging.info("Autostart %s", "enabled" if enabled else "disabled")
        icon_ref.update_menu()

    def setup(icon_ref: pystray.Icon) -> None:
        logging.info("Tray icon ready; log file: %s", log_path)

    icon = pystray.Icon(
        "local-photo-sharing",
        create_tray_icon_image(),
        APP_NAME,
        menu=pystray.Menu(
            pystray.MenuItem("Open Web UI", handle_open, default=True),
            pystray.MenuItem("Launch at startup", handle_toggle_autostart, checked=autostart_checked),
            pystray.MenuItem("Exit", handle_exit),
        ),
    )
    icon.run(setup=setup)


if __name__ == "__main__":
    main()
