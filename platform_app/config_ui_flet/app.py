from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any

import flet as ft

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.photo_share.config import build_default_config, get_config_path, load_config, write_config
from core.photo_share.runtime import get_app_base_dir
from core.photo_share.server import ServerRuntime, create_server_runtime

APP_TITLE = "照片共享设置"
TRAY_WINDOW_CLASS = "LocalPhotoSharingTrayWindow"
WM_USER = 0x0400
WM_RESTART_SERVICE = WM_USER + 21
DEFAULT_LIBRARY_DIRNAME = ".photo_share_library"
DEPLOY_DIR = get_app_base_dir() / ".deploy"
LOG_FILES = (
    ("托盘日志", DEPLOY_DIR / "tray-app.log"),
    ("服务日志", DEPLOY_DIR / "photo-share.log"),
    ("错误日志", DEPLOY_DIR / "photo-share.err.log"),
)


def padding_symmetric(horizontal: int | float = 0, vertical: int | float = 0) -> ft.Padding:
    return ft.Padding(left=horizontal, top=vertical, right=horizontal, bottom=vertical)


def border_all(width: int | float, color: str) -> ft.Border:
    return ft.Border.all(width, color)


def border_only(
    *,
    left: ft.BorderSide | None = None,
    top: ft.BorderSide | None = None,
    right: ft.BorderSide | None = None,
    bottom: ft.BorderSide | None = None,
) -> ft.Border:
    return ft.Border.only(left=left, top=top, right=right, bottom=bottom)


ALIGN_CENTER = ft.Alignment(0, 0)


def request_tray_restart() -> bool:
    if not sys.platform.startswith("win"):
        return False
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    hwnd = user32.FindWindowW(TRAY_WINDOW_CLASS, None)
    if not hwnd:
        return False
    return bool(user32.PostMessageW(hwnd, WM_RESTART_SERVICE, 0, 0))


class ConfigModel:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.config: dict[str, Any] = self._load_or_create()

    def _load_or_create(self) -> dict[str, Any]:
        if not self.config_path.exists():
            default_root = get_app_base_dir() / DEFAULT_LIBRARY_DIRNAME
            default_root.mkdir(parents=True, exist_ok=True)
            config = build_default_config(default_root)
            write_config(self.config_path, config)
            return config
        loaded = load_config(self.config_path)
        if loaded is None:
            default_root = get_app_base_dir() / DEFAULT_LIBRARY_DIRNAME
            default_root.mkdir(parents=True, exist_ok=True)
            config = build_default_config(default_root)
            write_config(self.config_path, config)
            return config
        return loaded

    @property
    def photo_folders(self) -> list[str]:
        values = self.config.get("photo_folders", [])
        if not isinstance(values, list):
            return []
        return [str(Path(item).expanduser()) for item in values if isinstance(item, str) and item.strip()]

    @property
    def default_save_folder(self) -> str:
        value = self.config.get("default_save_folder")
        if isinstance(value, str) and value.strip():
            return str(Path(value).expanduser())
        folders = self.photo_folders
        return folders[0] if folders else ""

    @property
    def host(self) -> str:
        value = self.config.get("host", "0.0.0.0")
        return value if isinstance(value, str) and value.strip() else "0.0.0.0"

    @property
    def port(self) -> int:
        try:
            return int(self.config.get("port", 8000))
        except (TypeError, ValueError):
            return 8000

    @property
    def local_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def save_library(self, folders: list[str], default_save_folder: str) -> None:
        normalized = dedupe_paths(folders)
        if not normalized:
            raise ValueError("至少需要保留一个照片库目录。")
        default_folder = str(Path(default_save_folder or normalized[0]).expanduser())
        if default_folder not in normalized:
            normalized.append(default_folder)
        for folder in normalized:
            Path(folder).expanduser().mkdir(parents=True, exist_ok=True)
        Path(default_folder).expanduser().mkdir(parents=True, exist_ok=True)
        self.config["photo_folders"] = normalized
        self.config["default_save_folder"] = default_folder
        write_config(self.config_path, self.config)

    def save_network(self, host: str, port_text: str) -> int:
        clean_host = host.strip() or "0.0.0.0"
        try:
            port = int(port_text.strip())
        except ValueError as exc:
            raise ValueError("端口必须是数字。") from exc
        if not 1 <= port <= 65535:
            raise ValueError("端口必须在 1 到 65535 之间。")
        self.config["host"] = clean_host
        self.config["port"] = port
        write_config(self.config_path, self.config)
        return port

    def reload(self) -> None:
        loaded = load_config(self.config_path)
        if loaded is None:
            raise RuntimeError(f"配置文件无法读取: {self.config_path}")
        self.config = loaded


class ServiceController:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.runtime: ServerRuntime | None = None
        self.error = ""

    @property
    def running(self) -> bool:
        return self.runtime is not None

    @property
    def local_url(self) -> str:
        if self.runtime is not None:
            return self.runtime.local_url
        config = load_config(self.config_path) or {}
        try:
            port = int(config.get("port", 8000))
        except (TypeError, ValueError):
            port = 8000
        return f"http://127.0.0.1:{port}"

    def start(self) -> None:
        if self.runtime is not None:
            return
        self.error = ""
        try:
            runtime = create_server_runtime(self.config_path)
            runtime.start_background()
            self.runtime = runtime
        except Exception as exc:
            self.error = str(exc)
            raise

    def stop(self) -> None:
        if self.runtime is None:
            return
        self.runtime.shutdown()
        thread = self.runtime.thread
        if thread is not None:
            thread.join(timeout=3)
        self.runtime = None

    def restart(self) -> None:
        if self.runtime is None:
            self.start()
            return
        self.error = ""
        try:
            self.runtime = self.runtime.restart()
        except Exception as exc:
            self.runtime = None
            self.error = str(exc)
            raise


def dedupe_paths(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        path = str(Path(value).expanduser()).strip()
        if not path:
            continue
        key = path.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Flet configuration UI for Local Photo Sharing.")
    parser.add_argument("--config", default=None, help="JSON config path. Defaults to the shared config.json.")
    parser.add_argument("--start-service", action="store_true", help="Start the local web service when the UI opens.")
    parser.add_argument("--managed-by-tray", action="store_true", help="The Windows tray process owns service start/restart.")
    return parser.parse_args()


def read_log_tail(path: Path, lines: int = 160) -> str:
    if not path.exists():
        return "日志文件还没有生成。"
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return f"无法读取日志: {exc}"
    tail = content[-lines:]
    return "\n".join(tail) if tail else "日志文件为空。"


def open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform.startswith("win"):
        subprocess.Popen(["explorer", str(path)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def choose_folder_native(title: str = "选择目录") -> str | None:
    if not sys.platform.startswith("win"):
        return None
    escaped_title = title.replace("'", "''")
    ps_script = f"""
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = '{escaped_title}'
$dialog.ShowNewFolderButton = $true
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {{
    Write-Output $dialog.SelectedPath
}} else {{
    Write-Output '__CANCEL__'
}}
"""
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-STA",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            ps_script,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "无法打开目录选择器。")
    selected = (result.stdout or "").strip()
    if not selected or selected == "__CANCEL__":
        return None
    return selected


def main(page: ft.Page) -> None:
    args = ARGS
    config_path = get_config_path(args.config)
    model = ConfigModel(config_path)
    service = ServiceController(config_path)
    managed_by_tray = bool(args.managed_by_tray)
    folders = model.photo_folders
    selected_index = 0
    default_folder = model.default_save_folder or (folders[0] if folders else "")
    active_page = "library"

    page.title = APP_TITLE
    page.window_width = 980
    page.window_height = 720
    page.window_min_width = 820
    page.window_min_height = 600
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 0
    page.bgcolor = "#EEF4F7"
    page.theme = ft.Theme(color_scheme_seed="#176B87", use_material3=True)

    status = ft.Text("就绪", size=13, color="#607180", max_lines=2, overflow=ft.TextOverflow.ELLIPSIS)
    service_badge_text = ft.Text("服务未启动", size=12, weight=ft.FontWeight.BOLD, color="#5F6F7C")
    service_badge = ft.Container(
        padding=padding_symmetric(horizontal=12, vertical=7),
        border_radius=999,
        bgcolor="#E4EBEF",
        content=service_badge_text,
    )

    folder_list = ft.ListView(spacing=8, auto_scroll=False, expand=True)
    default_dropdown = ft.Dropdown(label="默认上传目录", dense=True, expand=True)
    selected_path_text = ft.Text("未选择目录", size=12, color="#607180", max_lines=3, overflow=ft.TextOverflow.ELLIPSIS)
    host_field = ft.TextField(label="监听地址", value=model.host, dense=True, hint_text="0.0.0.0")
    port_field = ft.TextField(label="端口", value=str(model.port), dense=True, keyboard_type=ft.KeyboardType.NUMBER)
    local_url_text = ft.Text(model.local_url, size=14, selectable=True, weight=ft.FontWeight.BOLD, color="#0F5065")
    log_panels = ft.ListView(spacing=10, expand=True)
    content_host = ft.Container(expand=True)
    nav_buttons: dict[str, ft.Container] = {}

    def set_status(message: str, color: str | None = None) -> None:
        status.value = message
        status.color = color or "#607180"
        page.update()

    def refresh_service_badge() -> None:
        if managed_by_tray:
            service_badge.bgcolor = "#EAF7F8"
            service_badge_text.value = "服务由托盘程序管理"
            service_badge_text.color = "#0F5065"
            return
        if service.running:
            service_badge.bgcolor = "#DDF3EA"
            service_badge_text.value = f"服务运行中: {service.local_url}"
            service_badge_text.color = "#16704A"
        elif service.error:
            service_badge.bgcolor = "#FCE4E4"
            service_badge_text.value = "服务启动失败"
            service_badge_text.color = "#B3261E"
        else:
            service_badge.bgcolor = "#E4EBEF"
            service_badge_text.value = "服务未启动"
            service_badge_text.color = "#5F6F7C"

    def refresh_default_dropdown() -> None:
        nonlocal default_folder
        if default_folder not in folders and folders:
            default_folder = folders[0]
        default_dropdown.options = [ft.dropdown.Option(folder) for folder in folders]
        default_dropdown.value = default_folder if default_folder in folders else None

    def refresh_selected_text() -> None:
        if folders and 0 <= selected_index < len(folders):
            selected_path_text.value = folders[selected_index]
        else:
            selected_path_text.value = "未选择目录"

    def select_folder(index: int) -> None:
        nonlocal selected_index
        selected_index = index
        render_folders()

    def render_folders() -> None:
        folder_list.controls.clear()
        if not folders:
            folder_list.controls.append(
                ft.Container(
                    padding=24,
                    border_radius=10,
                    bgcolor="#F7FAFB",
                    border=border_all(1, "#D7E0E8"),
                    content=ft.Text("还没有照片库目录。请添加至少一个本机目录。", color="#607180"),
                )
            )
        for index, folder in enumerate(folders):
            active = index == selected_index
            is_default = folder == default_folder
            folder_list.controls.append(
                ft.Container(
                    padding=padding_symmetric(horizontal=14, vertical=12),
                    border_radius=10,
                    bgcolor="#EAF7F8" if active else "#FFFFFF",
                    border=border_all(1.2, "#7AC7CC" if active else "#D7E0E8"),
                    on_click=lambda _event, item_index=index: select_folder(item_index),
                    content=ft.Row(
                        controls=[
                            ft.Container(
                                width=34,
                                height=34,
                                border_radius=9,
                                bgcolor="#D8F0F1" if active else "#EEF4F7",
                                alignment=ALIGN_CENTER,
                                content=ft.Icon(ft.Icons.FOLDER_OUTLINED, size=19, color="#176B87"),
                            ),
                            ft.Column(
                                spacing=3,
                                expand=True,
                                controls=[
                                    ft.Text(folder, size=13, weight=ft.FontWeight.BOLD, overflow=ft.TextOverflow.ELLIPSIS),
                                    ft.Text("默认上传目录" if is_default else f"照片库 {index + 1}", size=12, color="#607180"),
                                ],
                            ),
                        ],
                    ),
                )
            )
        refresh_selected_text()
        refresh_default_dropdown()
        refresh_service_badge()
        page.update()

    def add_folder(path: str | None) -> None:
        nonlocal selected_index
        if not path:
            return
        normalized = str(Path(path).expanduser())
        if normalized in folders:
            set_status("这个目录已经在列表中。", "#A05A00")
            return
        folders.append(normalized)
        selected_index = len(folders) - 1
        set_status("已添加目录，保存后生效。")
        render_folders()

    def add_folder_from_dialog(_event: ft.ControlEvent | None = None) -> None:
        try:
            add_folder(choose_folder_native("选择要加入照片库的目录"))
        except Exception as exc:
            set_status(f"无法打开目录选择器: {exc}", "#B3261E")

    def remove_selected(_event: ft.ControlEvent | None = None) -> None:
        nonlocal selected_index, default_folder
        if len(folders) <= 1:
            set_status("至少需要保留一个照片库目录。", "#B3261E")
            return
        if not (0 <= selected_index < len(folders)):
            return
        removed = folders.pop(selected_index)
        if default_folder == removed:
            default_folder = folders[0]
        selected_index = min(selected_index, len(folders) - 1)
        set_status("已删除目录，保存后生效。")
        render_folders()

    def move_selected(delta: int) -> None:
        nonlocal selected_index
        target = selected_index + delta
        if not (0 <= selected_index < len(folders) and 0 <= target < len(folders)):
            return
        folders[selected_index], folders[target] = folders[target], folders[selected_index]
        selected_index = target
        set_status("目录顺序已调整，保存后生效。")
        render_folders()

    def on_default_changed(event: ft.ControlEvent) -> None:
        nonlocal default_folder
        default_folder = str(event.control.value or "")
        render_folders()

    default_dropdown.on_change = on_default_changed

    def save_library(_event: ft.ControlEvent | None = None) -> None:
        try:
            model.save_library(folders, default_folder)
            if managed_by_tray:
                if request_tray_restart():
                    set_status("照片库配置已保存，服务正在后台重启。", "#16704A")
                else:
                    set_status("照片库配置已保存，但没有找到托盘进程，请手动重启应用。", "#A05A00")
            else:
                service.restart()
                set_status("照片库配置已保存，服务已重启。", "#16704A")
            refresh_service_badge()
            page.update()
        except Exception as exc:
            set_status(f"保存失败: {exc}", "#B3261E")

    def save_network(_event: ft.ControlEvent | None = None) -> None:
        try:
            port = model.save_network(host_field.value or "", port_field.value or "")
            local_url_text.value = f"http://127.0.0.1:{port}"
            if managed_by_tray:
                if request_tray_restart():
                    set_status("网络配置已保存，服务正在后台重启。", "#16704A")
                else:
                    set_status("网络配置已保存，但没有找到托盘进程，请手动重启应用。", "#A05A00")
            else:
                service.restart()
                local_url_text.value = service.local_url
                set_status("网络配置已保存，服务已重启。", "#16704A")
            refresh_service_badge()
            page.update()
        except Exception as exc:
            set_status(f"保存失败: {exc}", "#B3261E")

    def start_service(_event: ft.ControlEvent | None = None) -> None:
        try:
            service.start()
            local_url_text.value = service.local_url
            set_status("服务已启动。", "#16704A")
        except Exception as exc:
            set_status(f"服务启动失败: {exc}", "#B3261E")
        refresh_service_badge()
        page.update()

    def stop_service(_event: ft.ControlEvent | None = None) -> None:
        service.stop()
        set_status("服务已停止。")
        refresh_service_badge()
        page.update()

    def restart_service(_event: ft.ControlEvent | None = None) -> None:
        try:
            service.restart()
            local_url_text.value = service.local_url
            set_status("服务已重启。", "#16704A")
        except Exception as exc:
            set_status(f"服务重启失败: {exc}", "#B3261E")
        refresh_service_badge()
        page.update()

    def open_web(_event: ft.ControlEvent | None = None) -> None:
        url = local_url_text.value or service.local_url
        webbrowser.open(url)
        set_status(f"已打开 {url}")

    def copy_diagnostics(_event: ft.ControlEvent | None = None) -> None:
        page.set_clipboard(build_diagnostics_json())
        set_status("诊断信息已复制到剪贴板。", "#16704A")

    def open_log_dir(_event: ft.ControlEvent | None = None) -> None:
        try:
            open_folder(DEPLOY_DIR)
            set_status(f"已打开日志目录: {DEPLOY_DIR}")
        except Exception as exc:
            set_status(f"无法打开日志目录: {exc}", "#B3261E")

    def build_diagnostics_json() -> str:
        snapshot = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "configPath": str(config_path),
            "appBaseDir": str(get_app_base_dir()),
            "projectRoot": str(PROJECT_ROOT),
            "photoFolders": folders,
            "defaultSaveFolder": default_folder,
            "host": host_field.value,
            "port": port_field.value,
            "serviceRunning": service.running,
            "serviceManagedByTray": managed_by_tray,
            "localUrl": local_url_text.value or service.local_url,
            "serviceError": service.error,
            "logFiles": {name: str(path) for name, path in LOG_FILES},
            "platform": sys.platform,
            "pid": os.getpid(),
        }
        return json.dumps(snapshot, ensure_ascii=False, indent=2)

    def refresh_logs(_event: ft.ControlEvent | None = None, update: bool = True) -> None:
        log_panels.controls = [
            ft.Container(
                padding=14,
                border_radius=10,
                bgcolor="#F7FAFB",
                border=border_all(1, "#D7E0E8"),
                content=ft.Column(
                    spacing=8,
                    controls=[
                        ft.Text(name, size=13, weight=ft.FontWeight.BOLD, color="#26343C"),
                        ft.Container(
                            height=180,
                            content=ft.ListView(
                                controls=[
                                    ft.Text(
                                        read_log_tail(path),
                                        size=12,
                                        selectable=True,
                                        font_family="Consolas",
                                        color="#26343C",
                                    )
                                ],
                                expand=True,
                                auto_scroll=False,
                            ),
                        ),
                    ],
                ),
            )
            for name, path in LOG_FILES
        ]
        if update:
            page.update()

    def diagnostics_summary() -> ft.Row:
        return ft.Row(
            spacing=10,
            controls=[
                ft.Container(
                    expand=True,
                    padding=14,
                    border_radius=10,
                    bgcolor="#F7FAFB",
                    border=border_all(1, "#D7E0E8"),
                    content=ft.Column(
                        spacing=6,
                        controls=[
                            ft.Text("配置文件", size=12, color="#607180"),
                            ft.Text(str(config_path), size=12, selectable=True, color="#26343C"),
                        ],
                    ),
                ),
                ft.Container(
                    width=230,
                    padding=14,
                    border_radius=10,
                    bgcolor="#F7FAFB",
                    border=border_all(1, "#D7E0E8"),
                    content=ft.Column(
                        spacing=6,
                        controls=[
                            ft.Text("本机地址", size=12, color="#607180"),
                            ft.Text(local_url_text.value or service.local_url, size=13, weight=ft.FontWeight.BOLD, color="#0F5065", selectable=True),
                        ],
                    ),
                ),
            ],
        )

    def log_panel() -> ft.Control:
        return ft.Container(
            expand=True,
            content=log_panels,
        )

    def nav_item(key: str, icon: str, label: str) -> ft.Container:
        selected = key == active_page
        item = ft.Container(
            padding=padding_symmetric(horizontal=12, vertical=10),
            border_radius=10,
            bgcolor="#D8F0F1" if selected else None,
            ink=True,
            on_click=lambda _event, page_key=key: show_page(page_key),
            content=ft.Row(
                spacing=10,
                controls=[
                    ft.Icon(icon, size=20, color="#176B87" if selected else "#607180"),
                    ft.Text(label, size=14, weight=ft.FontWeight.BOLD if selected else ft.FontWeight.NORMAL, color="#143642" if selected else "#4E5D68"),
                ],
            ),
        )
        nav_buttons[key] = item
        return item

    def update_nav() -> None:
        for key, item in nav_buttons.items():
            selected = key == active_page
            item.bgcolor = "#D8F0F1" if selected else None
            row = item.content
            if isinstance(row, ft.Row):
                icon = row.controls[0]
                text = row.controls[1]
                icon.color = "#176B87" if selected else "#607180"
                text.weight = ft.FontWeight.BOLD if selected else ft.FontWeight.NORMAL
                text.color = "#143642" if selected else "#4E5D68"

    def surface(content: ft.Control, expand: bool = False, padding: int = 18) -> ft.Container:
        return ft.Container(
            expand=expand,
            padding=padding,
            bgcolor="#FCFEFF",
            border_radius=12,
            border=border_all(1, "#D7E0E8"),
            shadow=ft.BoxShadow(blur_radius=18, spread_radius=0, color="#18000000", offset=ft.Offset(0, 8)),
            content=content,
        )

    def section_title(title: str, desc: str) -> ft.Column:
        return ft.Column(
            spacing=4,
            controls=[
                ft.Text(title, size=20, weight=ft.FontWeight.BOLD, color="#18232B"),
                ft.Text(desc, size=13, color="#607180"),
            ],
        )

    def selected_folder_details() -> ft.Column:
        path = folders[selected_index] if folders and 0 <= selected_index < len(folders) else "未选择目录"
        return ft.Column(
            spacing=8,
            controls=[
                ft.Text("当前选中", size=12, color="#607180"),
                ft.Text(path, size=13, weight=ft.FontWeight.BOLD, color="#26343C", selectable=True),
            ],
        )

    def library_view() -> ft.Control:
        return ft.Row(
            expand=True,
            spacing=16,
            controls=[
                surface(
                    ft.Column(
                        expand=True,
                        spacing=14,
                        controls=[
                            ft.Row(
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                controls=[
                                    section_title("照片库管理", "多个本机目录会组合成一个虚拟照片库。"),
                                    ft.FilledButton(
                                        "添加目录",
                                        icon=ft.Icons.ADD,
                                        on_click=add_folder_from_dialog,
                                    ),
                                ],
                            ),
                            ft.Container(expand=True, content=folder_list),
                        ],
                    ),
                    expand=True,
                ),
                surface(
                    ft.Column(
                        width=360,
                        spacing=14,
                        controls=[
                            section_title("目录操作", "选择目录后可以调整顺序或删除。"),
                            selected_folder_details(),
                            ft.Row(
                                spacing=8,
                                controls=[
                                    ft.OutlinedButton("上移", icon=ft.Icons.ARROW_UPWARD, expand=True, on_click=lambda _event: move_selected(-1)),
                                    ft.OutlinedButton("下移", icon=ft.Icons.ARROW_DOWNWARD, expand=True, on_click=lambda _event: move_selected(1)),
                                ],
                            ),
                            ft.OutlinedButton("删除选中目录", icon=ft.Icons.DELETE_OUTLINE, on_click=remove_selected),
                            ft.Divider(height=18),
                            ft.Text("默认上传目录", size=12, color="#607180"),
                            default_dropdown,
                            ft.FilledButton("保存照片库并重启服务", icon=ft.Icons.SAVE_OUTLINED, on_click=save_library),
                            ft.Text("保存后由托盘进程在后台重启服务，局域网访问会短暂中断。", size=12, color="#607180"),
                        ],
                    ),
                    padding=18,
                ),
            ],
        )

    def network_view() -> ft.Control:
        return ft.Column(
            expand=True,
            controls=[
                surface(
                    ft.Column(
                        spacing=18,
                        controls=[
                            section_title("网络 / 端口", "配置本地 Web 服务监听地址和端口。保存后服务会在后台静默重启。"),
                            ft.Row(spacing=12, controls=[ft.Container(expand=True, content=host_field), ft.Container(width=180, content=port_field)]),
                            ft.Container(
                                padding=14,
                                border_radius=10,
                                bgcolor="#F7FAFB",
                                border=border_all(1, "#D7E0E8"),
                                content=ft.Column(
                                    spacing=6,
                                    controls=[
                                        ft.Text("本机访问地址", size=12, color="#607180"),
                                        local_url_text,
                                        ft.Text("局域网设备访问时，把 127.0.0.1 换成这台电脑的局域网 IP。", size=12, color="#607180"),
                                    ],
                                ),
                            ),
                            ft.Row(
                                wrap=True,
                                spacing=8,
                                controls=[
                                    ft.FilledButton("保存网络配置并重启服务", icon=ft.Icons.SAVE_OUTLINED, on_click=save_network),
                                ],
                            ),
                        ],
                    )
                ),
            ],
        )

    def diagnostics_view() -> ft.Control:
        refresh_logs(update=False)
        return ft.Column(
            expand=True,
            spacing=12,
            controls=[
                surface(
                    ft.Column(
                        spacing=12,
                        controls=[
                            section_title("日志 / 诊断", "查看本机运行状态和最近日志，方便定位启动、端口、目录问题。"),
                            diagnostics_summary(),
                            ft.Row(
                                wrap=True,
                                spacing=8,
                                controls=[
                                    ft.FilledButton("刷新日志", icon=ft.Icons.REFRESH, on_click=refresh_logs),
                                    ft.OutlinedButton("打开日志目录", icon=ft.Icons.FOLDER_OPEN, on_click=open_log_dir),
                                    ft.OutlinedButton("复制诊断信息", icon=ft.Icons.CONTENT_COPY, on_click=copy_diagnostics),
                                ],
                            ),
                        ],
                    )
                ),
                surface(log_panel(), expand=True, padding=12),
            ],
        )

    def show_page(key: str) -> None:
        nonlocal active_page
        active_page = key
        update_nav()
        if key == "network":
            content_host.content = network_view()
        elif key == "diagnostics":
            content_host.content = diagnostics_view()
        else:
            content_host.content = library_view()
        page.update()

    sidebar = ft.Container(
        width=220,
        padding=18,
        bgcolor="#F7FAFB",
        border=border_only(right=ft.BorderSide(1, "#D7E0E8")),
        content=ft.Column(
            spacing=14,
            controls=[
                ft.Column(
                    spacing=2,
                    controls=[
                        ft.Text("本机配置", size=22, weight=ft.FontWeight.BOLD, color="#18232B"),
                        ft.Text("Local Photo Sharing", size=12, color="#607180"),
                    ],
                ),
                ft.Divider(height=12),
                nav_item("library", ft.Icons.PHOTO_LIBRARY_OUTLINED, "照片库管理"),
                nav_item("network", ft.Icons.LAN_OUTLINED, "网络 / 端口"),
                nav_item("diagnostics", ft.Icons.TERMINAL_OUTLINED, "日志 / 诊断"),
                ft.Container(expand=True),
                service_badge,
            ],
        ),
    )

    page.add(
        ft.Column(
            expand=True,
            spacing=0,
            controls=[
                ft.Row(
                    expand=True,
                    spacing=0,
                    controls=[
                        sidebar,
                        ft.Container(
                            expand=True,
                            padding=22,
                            content=content_host,
                        ),
                    ],
                ),
                ft.Container(
                    padding=padding_symmetric(horizontal=22, vertical=10),
                    bgcolor="#FCFEFF",
                    border=border_only(top=ft.BorderSide(1, "#D7E0E8")),
                    content=status,
                ),
            ],
        )
    )

    render_folders()
    show_page("library")
    if args.start_service:
        start_service()


if __name__ == "__main__":
    ARGS = parse_args()
    ft.run(main)
