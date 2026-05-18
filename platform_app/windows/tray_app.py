from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import os
import subprocess
import webbrowser
from pathlib import Path
import sys
import winreg

from core.photo_share.config import build_default_config, get_config_path, load_config, parse_args, write_config
from core.photo_share.runtime import get_app_base_dir, get_resource_base_dir
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
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x00000010
TRAY_ICON_RELATIVE_PATH = Path("assets") / "icons8-photo-gallery-96.ico"
CMD_OPEN = 1001
CMD_MANAGE_FOLDERS = 1002
CMD_TOGGLE_AUTOSTART = 1003
CMD_EXIT = 1004

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


def choose_photo_roots(reason: str, default_path: Path) -> list[Path] | None:
    escaped_reason = reason.replace("'", "''")
    escaped_default = str(default_path).replace("'", "''")
    ps_script = f"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$folders = New-Object System.Collections.Generic.List[string]
$defaultPath = '{escaped_default}'
$intro = [System.Windows.Forms.MessageBox]::Show(
    '{escaped_reason}`n`n是 = 先添加默认目录`n否 = 自己选择目录`n取消 = 退出引导',
    '{APP_NAME}',
    [System.Windows.Forms.MessageBoxButtons]::YesNoCancel,
    [System.Windows.Forms.MessageBoxIcon]::Question
)
if ($intro -eq [System.Windows.Forms.DialogResult]::Cancel) {{
    Write-Output '__CANCEL__'
    exit 0
}}
if ($intro -eq [System.Windows.Forms.DialogResult]::Yes) {{
    $folders.Add($defaultPath)
}}
while ($true) {{
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = '选择要加入照片库的目录'
    $dialog.SelectedPath = $defaultPath
    $dialog.ShowNewFolderButton = $true
    if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {{
        if (-not $folders.Contains($dialog.SelectedPath)) {{
            $folders.Add($dialog.SelectedPath)
        }}
    }}
    $summary = if ($folders.Count -gt 0) {{ [string]::Join("`n", $folders.ToArray()) }} else {{ '(none yet)' }}
    $again = [System.Windows.Forms.MessageBox]::Show(
        "当前照片库目录:`n$summary`n`n继续添加目录吗？",
        '{APP_NAME}',
        [System.Windows.Forms.MessageBoxButtons]::YesNo,
        [System.Windows.Forms.MessageBoxIcon]::Question
    )
    if ($again -ne [System.Windows.Forms.DialogResult]::Yes) {{
        break
    }}
}}
if ($folders.Count -eq 0) {{
    Write-Output '__CANCEL__'
}} else {{
    $folders | ForEach-Object {{ Write-Output $_ }}
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
    selected = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    if not selected or selected == ["__CANCEL__"]:
        return None
    return [Path(item).expanduser() for item in selected if item != "__CANCEL__"]


def manage_photo_folders(config_path: Path) -> list[Path] | None:
    config = load_config(config_path)
    if config is None:
        return None
    existing = [str(Path(item).expanduser()) for item in config.get("photo_folders", []) if isinstance(item, str) and item.strip()]
    default_save = str(Path(config.get("default_save_folder") or (existing[0] if existing else default_photo_root())).expanduser())
    escaped_config = str(config_path).replace("'", "''")
    escaped_existing = "|".join(item.replace("|", " ") for item in existing).replace("'", "''")
    escaped_default = default_save.replace("|", " ").replace("'", "''")
    ps_script = f"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$form = New-Object System.Windows.Forms.Form
$form.Text = '照片库目录'
$form.StartPosition = 'CenterScreen'
$form.Width = 780
$form.Height = 560
$form.MinimizeBox = $false
$form.MaximizeBox = $false
$form.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::FixedDialog
$form.ShowIcon = $false
$form.BackColor = [System.Drawing.Color]::FromArgb(246, 248, 250)
$form.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 9)

$accent = [System.Drawing.Color]::FromArgb(23, 107, 135)
$accentDark = [System.Drawing.Color]::FromArgb(15, 80, 101)
$panel = [System.Drawing.Color]::White
$muted = [System.Drawing.Color]::FromArgb(96, 113, 128)
$line = [System.Drawing.Color]::FromArgb(215, 224, 232)

function Set-ButtonStyle($button, [bool]$primary = $false) {{
    $button.Height = 36
    $button.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
    $button.FlatAppearance.BorderSize = 1
    $button.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 9, [System.Drawing.FontStyle]::Bold)
    if ($primary) {{
        $button.BackColor = $accent
        $button.ForeColor = [System.Drawing.Color]::White
        $button.FlatAppearance.BorderColor = $accentDark
    }} else {{
        $button.BackColor = [System.Drawing.Color]::White
        $button.ForeColor = $accentDark
        $button.FlatAppearance.BorderColor = $line
    }}
}}

$title = New-Object System.Windows.Forms.Label
$title.Text = '管理照片库目录'
$title.Left = 24
$title.Top = 22
$title.Width = 320
$title.Height = 34
$title.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 18, [System.Drawing.FontStyle]::Bold)
$title.ForeColor = [System.Drawing.Color]::FromArgb(28, 35, 43)
$form.Controls.Add($title)

$subtitle = New-Object System.Windows.Forms.Label
$subtitle.Text = '这些本机目录会组合成网页中的照片库入口。修改后会自动重启本机服务。'
$subtitle.Left = 26
$subtitle.Top = 62
$subtitle.Width = 660
$subtitle.Height = 24
$subtitle.ForeColor = $muted
$form.Controls.Add($subtitle)

$card = New-Object System.Windows.Forms.Panel
$card.Left = 24
$card.Top = 100
$card.Width = 710
$card.Height = 330
$card.BackColor = $panel
$card.BorderStyle = [System.Windows.Forms.BorderStyle]::FixedSingle
$form.Controls.Add($card)

$listLabel = New-Object System.Windows.Forms.Label
$listLabel.Text = '照片库目录'
$listLabel.Left = 18
$listLabel.Top = 14
$listLabel.Width = 160
$listLabel.Height = 24
$listLabel.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 10, [System.Drawing.FontStyle]::Bold)
$card.Controls.Add($listLabel)

$hintLabel = New-Object System.Windows.Forms.Label
$hintLabel.Text = '第一项会作为默认浏览入口；可以用上移、下移调整顺序。'
$hintLabel.Left = 18
$hintLabel.Top = 40
$hintLabel.Width = 520
$hintLabel.Height = 22
$hintLabel.ForeColor = $muted
$card.Controls.Add($hintLabel)

$list = New-Object System.Windows.Forms.ListBox
$list.Left = 18
$list.Top = 72
$list.Width = 510
$list.Height = 238
$list.HorizontalScrollbar = $true
$list.BorderStyle = [System.Windows.Forms.BorderStyle]::FixedSingle
$list.BackColor = [System.Drawing.Color]::FromArgb(252, 253, 254)
$card.Controls.Add($list)

$addButton = New-Object System.Windows.Forms.Button
$addButton.Text = '添加...'
$addButton.Left = 552
$addButton.Top = 72
$addButton.Width = 126
Set-ButtonStyle $addButton $true
$card.Controls.Add($addButton)

$removeButton = New-Object System.Windows.Forms.Button
$removeButton.Text = '删除'
$removeButton.Left = 552
$removeButton.Top = 116
$removeButton.Width = 126
Set-ButtonStyle $removeButton
$card.Controls.Add($removeButton)

$upButton = New-Object System.Windows.Forms.Button
$upButton.Text = '上移'
$upButton.Left = 552
$upButton.Top = 176
$upButton.Width = 126
Set-ButtonStyle $upButton
$card.Controls.Add($upButton)

$downButton = New-Object System.Windows.Forms.Button
$downButton.Text = '下移'
$downButton.Left = 552
$downButton.Top = 220
$downButton.Width = 126
Set-ButtonStyle $downButton
$card.Controls.Add($downButton)

$defaultLabel = New-Object System.Windows.Forms.Label
$defaultLabel.Text = '默认上传目录'
$defaultLabel.Left = 26
$defaultLabel.Top = 452
$defaultLabel.Width = 170
$defaultLabel.Height = 24
$defaultLabel.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 10, [System.Drawing.FontStyle]::Bold)
$form.Controls.Add($defaultLabel)

$defaultBox = New-Object System.Windows.Forms.ComboBox
$defaultBox.Left = 150
$defaultBox.Top = 448
$defaultBox.Width = 390
$defaultBox.Height = 34
$defaultBox.DropDownStyle = [System.Windows.Forms.ComboBoxStyle]::DropDownList
$form.Controls.Add($defaultBox)

$okButton = New-Object System.Windows.Forms.Button
$okButton.Text = '保存并重启服务'
$okButton.Left = 548
$okButton.Top = 496
$okButton.Width = 186
$okButton.DialogResult = [System.Windows.Forms.DialogResult]::OK
$form.AcceptButton = $okButton
Set-ButtonStyle $okButton $true
$form.Controls.Add($okButton)

$cancelButton = New-Object System.Windows.Forms.Button
$cancelButton.Text = '取消'
$cancelButton.Left = 412
$cancelButton.Top = 496
$cancelButton.Width = 120
$cancelButton.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
$form.CancelButton = $cancelButton
Set-ButtonStyle $cancelButton
$form.Controls.Add($cancelButton)

function Sync-DefaultBox {{
    $current = $defaultBox.SelectedItem
    $defaultBox.Items.Clear()
    foreach ($item in $list.Items) {{ [void]$defaultBox.Items.Add($item) }}
    if ($current -and $defaultBox.Items.Contains($current)) {{
        $defaultBox.SelectedItem = $current
    }} elseif ($defaultBox.Items.Count -gt 0) {{
        $defaultBox.SelectedIndex = 0
    }}
    $removeButton.Enabled = $list.Items.Count -gt 1
    $okButton.Enabled = $list.Items.Count -gt 0
}}

$initial = '{escaped_existing}'
if ($initial.Length -gt 0) {{
    foreach ($item in $initial.Split('|')) {{
        if ($item.Trim().Length -gt 0 -and -not $list.Items.Contains($item)) {{ [void]$list.Items.Add($item) }}
    }}
}}
Sync-DefaultBox
$default = '{escaped_default}'
if ($defaultBox.Items.Contains($default)) {{ $defaultBox.SelectedItem = $default }}

$addButton.Add_Click({{
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = '选择要加入照片库的目录'
    $dialog.ShowNewFolderButton = $true
    if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {{
        if (-not $list.Items.Contains($dialog.SelectedPath)) {{
            [void]$list.Items.Add($dialog.SelectedPath)
            $list.SelectedItem = $dialog.SelectedPath
            Sync-DefaultBox
        }} else {{
            [System.Windows.Forms.MessageBox]::Show('这个目录已经在列表中。', '照片库目录', [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Information) | Out-Null
        }}
    }}
}})

$removeButton.Add_Click({{
    $index = $list.SelectedIndex
    if ($index -ge 0 -and $list.Items.Count -gt 1) {{
        $list.Items.RemoveAt($index)
        if ($list.Items.Count -gt 0) {{ $list.SelectedIndex = [Math]::Min($index, $list.Items.Count - 1) }}
        Sync-DefaultBox
    }}
}})

$upButton.Add_Click({{
    $index = $list.SelectedIndex
    if ($index -gt 0) {{
        $item = $list.Items[$index]
        $list.Items.RemoveAt($index)
        $list.Items.Insert($index - 1, $item)
        $list.SelectedIndex = $index - 1
        Sync-DefaultBox
    }}
}})

$downButton.Add_Click({{
    $index = $list.SelectedIndex
    if ($index -ge 0 -and $index -lt $list.Items.Count - 1) {{
        $item = $list.Items[$index]
        $list.Items.RemoveAt($index)
        $list.Items.Insert($index + 1, $item)
        $list.SelectedIndex = $index + 1
        Sync-DefaultBox
    }}
}})

if ($form.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {{
    Write-Output '__CANCEL__'
    exit 0
}}
foreach ($item in $list.Items) {{ Write-Output "ROOT::$item" }}
Write-Output "DEFAULT::$($defaultBox.SelectedItem)"
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
        raise RuntimeError(f"Unable to open folder manager: {result.stderr.strip() or result.stdout.strip()}")
    lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    if not lines or lines == ["__CANCEL__"]:
        return None
    roots = [Path(line[len("ROOT::"):]).expanduser() for line in lines if line.startswith("ROOT::")]
    default_lines = [line[len("DEFAULT::"):] for line in lines if line.startswith("DEFAULT::")]
    if not roots:
        return None
    default = Path(default_lines[-1]).expanduser() if default_lines else roots[0]
    config["photo_folders"] = [str(root) for root in roots]
    config["default_save_folder"] = str(default)
    for root in roots:
        root.mkdir(parents=True, exist_ok=True)
    default.mkdir(parents=True, exist_ok=True)
    write_config(config_path, config)
    return roots


def write_initial_photo_config(config_path: Path, photo_roots: list[Path]) -> None:
    for photo_root in photo_roots:
        photo_root.mkdir(parents=True, exist_ok=True)
    write_config(config_path, build_default_config(photo_roots))


def ensure_tray_config_ready(config_path: Path) -> bool:
    if config_path.exists():
        return True
    selected = choose_photo_roots(
        "首次启动：请选择一个或多个照片库目录。",
        default_photo_root(),
    )
    if selected is None:
        logging.info("Initial setup cancelled before config creation")
        return False
    write_initial_photo_config(config_path, selected)
    logging.info("Created initial config at %s with photo roots %s", config_path, selected)
    return True


def prompt_repair_photo_root(config_path: Path, error: Exception) -> bool:
    message = (
        "当前照片库目录不存在或不可用。\n\n"
        f"{error}\n\n"
        "是 = 使用下面显示的默认目录\n否 = 选择另一个目录"
    )
    selected = choose_photo_root(message, default_photo_root())
    if selected is None:
        logging.info("Photo root repair cancelled")
        return False
    write_initial_photo_config(config_path, [selected])
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
user32.LoadImageW.argtypes = [
    wintypes.HINSTANCE,
    wintypes.LPCWSTR,
    wintypes.UINT,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
]
user32.LoadImageW.restype = wintypes.HANDLE
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
        self.hicon = self._load_icon()
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

    def _load_icon(self):
        icon_path = get_resource_base_dir() / TRAY_ICON_RELATIVE_PATH
        if icon_path.is_file():
            hicon = user32.LoadImageW(None, str(icon_path), IMAGE_ICON, 0, 0, LR_LOADFROMFILE)
            if hicon:
                logging.info("Loaded tray icon: %s", icon_path)
                return hicon
            logging.warning("Failed to load tray icon from %s; falling back to system icon", icon_path)
        else:
            logging.warning("Tray icon file not found: %s; falling back to system icon", icon_path)
        return user32.LoadIconW(None, ctypes.c_wchar_p(IDI_APPLICATION))

    def _delete_icon(self) -> None:
        if self.nid is not None:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self.nid))
            self.nid = None

    def _show_menu(self) -> None:
        menu = user32.CreatePopupMenu()
        check_windows_result(menu, "CreatePopupMenu")
        user32.AppendMenuW(menu, MF_STRING, CMD_OPEN, "打开网页")
        user32.AppendMenuW(menu, MF_STRING, CMD_MANAGE_FOLDERS, "管理照片库目录...")
        checked = MF_CHECKED if is_autostart_enabled() else MF_UNCHECKED
        user32.AppendMenuW(menu, MF_STRING | checked, CMD_TOGGLE_AUTOSTART, "开机启动")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, CMD_EXIT, "退出")
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
        elif command == CMD_MANAGE_FOLDERS:
            logging.info("Opening photo folder manager")
            try:
                updated = manage_photo_folders(self.runtime.config_path)
            except Exception:
                logging.exception("Photo folder manager failed")
                return
            if updated is not None:
                logging.info("Photo folders updated; restarting service")
                self.runtime = self.runtime.restart()
                print_startup_summary(self.runtime)
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

    runtime.start_background()

    logging.info("Tray window starting; log file: %s", log_path)
    NativeTrayIcon(runtime).run()


if __name__ == "__main__":
    main()
