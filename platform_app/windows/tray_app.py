from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import os
import subprocess
import threading
import webbrowser
from pathlib import Path
import sys
import winreg

from core.photo_share.config import build_default_config, get_config_path, parse_args, write_config
from core.photo_share.runtime import get_app_base_dir
from core.photo_share.server import ServerRuntime, create_server_runtime

APP_NAME = "Local Photo Sharing"
AUTOSTART_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_VALUE_NAME = "LocalPhotoSharingTray"
DEFAULT_LIBRARY_DIRNAME = ".photo_share_library"

WM_DESTROY = 0x0002
WM_COMMAND = 0x0111
WM_USER = 0x0400
WM_TRAYICON = WM_USER + 20
WM_RBUTTONUP = 0x0205
WM_LBUTTONDBLCLK = 0x0203
NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
MF_STRING = 0x00000000
MF_SEPARATOR = 0x00000800
MF_CHECKED = 0x00000008
MF_UNCHECKED = 0x00000000
TPM_RETURNCMD = 0x00000100
TPM_RIGHTBUTTON = 0x00000002
IDI_APPLICATION = 32512
CMD_OPEN = 1001
CMD_TOGGLE_AUTOSTART = 1002
CMD_EXIT = 1003

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)


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
    return get_app_base_dir() / DEFAULT_LIBRARY_DIRNAME


def choose_photo_root(reason: str, default_path: Path) -> Path | None:
    escaped_reason = reason.replace("'", "''")
    escaped_default = str(default_path).replace("'", "''")
    ps_script = f"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$message = '{escaped_reason}`n`nDefault folder:`n{escaped_default}'
$choice = [System.Windows.Forms.MessageBox]::Show(
    $message,
    '{APP_NAME}',
    [System.Windows.Forms.MessageBoxButtons]::YesNoCancel,
    [System.Windows.Forms.MessageBoxIcon]::Question
)
if ($choice -eq [System.Windows.Forms.DialogResult]::Cancel) {{
    Write-Output '__CANCEL__'
    exit 0
}}
if ($choice -eq [System.Windows.Forms.DialogResult]::Yes) {{
    Write-Output '{escaped_default}'
    exit 0
}}
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = '{APP_NAME}'
$dialog.SelectedPath = '{escaped_default}'
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
        raise RuntimeError(f"Unable to open folder picker: {result.stderr.strip() or result.stdout.strip()}")
    selected = (result.stdout or "").strip()
    if not selected or selected == "__CANCEL__":
        return None
    return Path(selected).expanduser()


def write_initial_photo_config(config_path: Path, photo_root: Path) -> None:
    photo_root.mkdir(parents=True, exist_ok=True)
    write_config(config_path, build_default_config(photo_root))


def ensure_tray_config_ready(config_path: Path) -> bool:
    if config_path.exists():
        return True
    selected = choose_photo_root(
        "First launch: choose a folder for your photo library.\n\n"
        "Yes = use the default folder shown below\n"
        "No = choose another folder",
        default_photo_root(),
    )
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
        "Yes = use the default folder shown below\nNo = choose another folder"
    )
    selected = choose_photo_root(message, default_photo_root())
    if selected is None:
        logging.info("Photo root repair cancelled")
        return False
    write_initial_photo_config(config_path, selected)
    logging.info("Updated config at %s with repaired photo root %s", config_path, selected)
    return True


class WNDCLASS(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HCURSOR),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class NOTIFYICONDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uTimeoutOrVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", wintypes.HICON),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASS)]
user32.RegisterClassW.restype = wintypes.ATOM
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    wintypes.HMENU,
    wintypes.HINSTANCE,
    wintypes.LPVOID,
]
user32.CreateWindowExW.restype = wintypes.HWND
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
user32.LoadIconW.restype = wintypes.HICON
user32.CreatePopupMenu.restype = wintypes.HMENU
user32.TrackPopupMenu.argtypes = [
    wintypes.HMENU,
    wintypes.UINT,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    wintypes.LPVOID,
]
user32.TrackPopupMenu.restype = wintypes.UINT
shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATA)]
shell32.Shell_NotifyIconW.restype = wintypes.BOOL


def check_windows_result(result, action: str) -> None:
    if not result:
        error = ctypes.get_last_error()
        raise ctypes.WinError(error, action)


class NativeTrayIcon:
    def __init__(self, runtime: ServerRuntime):
        self.runtime = runtime
        self.class_name = "LocalPhotoSharingTrayWindow"
        self.instance = ctypes.windll.kernel32.GetModuleHandleW(None)
        self.hwnd = None
        self.hicon = None
        self.wndproc = WNDPROC(self._wndproc)
        self.nid = None

    def run(self) -> None:
        self._create_window()
        self._add_icon()
        logging.info("Native tray icon registered")
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        self._delete_icon()

    def _create_window(self) -> None:
        wndclass = WNDCLASS()
        wndclass.lpfnWndProc = self.wndproc
        wndclass.hInstance = self.instance
        wndclass.lpszClassName = self.class_name
        user32.RegisterClassW(ctypes.byref(wndclass))
        self.hwnd = user32.CreateWindowExW(
            0,
            self.class_name,
            APP_NAME,
            0,
            0,
            0,
            0,
            0,
            None,
            None,
            self.instance,
            None,
        )
        check_windows_result(self.hwnd, "CreateWindowExW")

    def _add_icon(self) -> None:
        self.hicon = user32.LoadIconW(None, ctypes.c_wchar_p(IDI_APPLICATION))
        check_windows_result(self.hicon, "LoadIconW")
        nid = NOTIFYICONDATA()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATA)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAYICON
        nid.hIcon = self.hicon
        nid.szTip = APP_NAME
        check_windows_result(shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)), "Shell_NotifyIconW(NIM_ADD)")
        self.nid = nid

    def _delete_icon(self) -> None:
        if self.nid is not None:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self.nid))
            self.nid = None

    def _show_menu(self) -> None:
        menu = user32.CreatePopupMenu()
        check_windows_result(menu, "CreatePopupMenu")
        user32.AppendMenuW(menu, MF_STRING, CMD_OPEN, "Open Web UI")
        checked = MF_CHECKED if is_autostart_enabled() else MF_UNCHECKED
        user32.AppendMenuW(menu, MF_STRING | checked, CMD_TOGGLE_AUTOSTART, "Launch at startup")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, CMD_EXIT, "Exit")
        point = POINT()
        user32.GetCursorPos(ctypes.byref(point))
        user32.SetForegroundWindow(self.hwnd)
        command = user32.TrackPopupMenu(menu, TPM_RETURNCMD | TPM_RIGHTBUTTON, point.x, point.y, 0, self.hwnd, None)
        user32.DestroyMenu(menu)
        if command:
            self._handle_command(command)

    def _handle_command(self, command: int) -> None:
        if command == CMD_OPEN:
            logging.info("Opening browser: %s", self.runtime.local_url)
            open_in_browser(self.runtime)
        elif command == CMD_TOGGLE_AUTOSTART:
            enabled = not is_autostart_enabled()
            set_autostart_enabled(enabled)
            logging.info("Autostart %s", "enabled" if enabled else "disabled")
        elif command == CMD_EXIT:
            logging.info("Exit requested from tray icon")
            self.runtime.shutdown()
            user32.DestroyWindow(self.hwnd)

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAYICON:
            if lparam == WM_RBUTTONUP:
                self._show_menu()
                return 0
            if lparam == WM_LBUTTONDBLCLK:
                self._handle_command(CMD_OPEN)
                return 0
        if msg == WM_COMMAND:
            self._handle_command(wparam & 0xFFFF)
            return 0
        if msg == WM_DESTROY:
            self._delete_icon()
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


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

    logging.info("Tray window starting; log file: %s", log_path)
    NativeTrayIcon(runtime).run()


if __name__ == "__main__":
    main()
