from __future__ import annotations

import logging
import os
import threading
import webbrowser
from pathlib import Path
import sys
from tkinter import TclError, Tk, filedialog, messagebox
import winreg

import pystray
from PIL import Image, ImageDraw

from core.photo_share.config import build_default_config, get_config_path, parse_args, write_config
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


def default_photo_root() -> Path:
    return get_app_base_dir()


def with_hidden_tk(callback):
    root = Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        return callback(root)
    finally:
        root.destroy()


def choose_photo_root(reason: str, default_path: Path) -> Path | None:
    def show_dialog(root: Tk) -> Path | None:
        choice = messagebox.askyesnocancel(
            APP_NAME,
            f"{reason}\n\nDefault folder:\n{default_path}",
            parent=root,
        )
        if choice is None:
            return None
        if choice:
            return default_path
        selected = filedialog.askdirectory(
            parent=root,
            title=APP_NAME,
            mustexist=False,
            initialdir=str(default_path),
        )
        if not selected:
            return None
        return Path(selected).expanduser()

    try:
        selected = with_hidden_tk(show_dialog)
    except TclError as exc:
        raise RuntimeError("Unable to open folder picker for initial configuration.") from exc
    return selected


def write_initial_photo_config(config_path: Path, photo_root: Path) -> None:
    photo_root.mkdir(parents=True, exist_ok=True)
    write_config(config_path, build_default_config(photo_root))


def ensure_tray_config_ready(config_path: Path) -> bool:
    if config_path.exists():
        return True
    selected = choose_photo_root("First launch: choose a folder for your photo library.\n\nYes = use the default folder\nNo = choose another folder", default_photo_root())
    if selected is None:
        logging.info("Initial setup cancelled before config creation")
        return False
    write_initial_photo_config(config_path, selected)
    logging.info("Created initial config at %s with photo root %s", config_path, selected)
    return True


def prompt_repair_photo_root(config_path: Path, error: Exception) -> bool:
    message = (
        "The current photo library folder is missing or invalid.\n\n"
        f"{error}\n\n"
        "Yes = use the default folder\nNo = choose another folder"
    )
    selected = choose_photo_root(message, default_photo_root())
    if selected is None:
        logging.info("Photo root repair cancelled")
        return False
    write_initial_photo_config(config_path, selected)
    logging.info("Updated config at %s with repaired photo root %s", config_path, selected)
    return True


def main() -> None:
    log_path = configure_logging()
    args = parse_args()
    config_path = get_config_path(args.config)
    if not ensure_tray_config_ready(config_path):
        return
    try:
        runtime = create_server_runtime(config_path)
    except ValueError as error:
        if "Photo root does not exist or is not a folder" not in str(error):
            raise
        if not prompt_repair_photo_root(config_path, error):
            return
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
