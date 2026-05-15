# 运行与配置

本文收纳根 README 中不适合放在首页的运行细节、配置字段和平台说明。

## 安装和启动

推荐用 `platform_app/shell/deploy` 下的脚本安装依赖、初始化配置并启动服务。

Windows PowerShell：

```powershell
.\platform_app\shell\deploy\deploy.ps1 install
.\platform_app\shell\deploy\deploy.ps1 init
.\platform_app\shell\deploy\deploy.ps1 start
```

Linux / macOS：

```bash
chmod +x ./platform_app/shell/deploy/deploy.sh
./platform_app/shell/deploy/deploy.sh install
./platform_app/shell/deploy/deploy.sh init
./platform_app/shell/deploy/deploy.sh start
```

后台运行：

```powershell
.\platform_app\shell\deploy\deploy.ps1 start-bg
.\platform_app\shell\deploy\deploy.ps1 status
.\platform_app\shell\deploy\deploy.ps1 logs
.\platform_app\shell\deploy\deploy.ps1 stop
```

直接启动：

```powershell
.\.venv\Scripts\python.exe platform_app\shell\app.py
```

先预生成所有缩略图缓存，再启动 Web 服务：

```powershell
.\.venv\Scripts\python.exe platform_app\shell\app.py warmup
```

指定配置文件路径：

```powershell
.\.venv\Scripts\python.exe platform_app\shell\app.py --config D:\photo-share-config.json
```

## 配置文件

首次启动如果没有 `config.json`，shell 入口会在终端里询问图库目录，直接回车可使用默认项目根目录；Windows 托盘入口会弹出对话框，默认使用 EXE 所在目录，也可以改选其他目录。确认后程序会创建初始配置并继续启动服务。

当前配置使用最新格式，不保留旧字段兼容。

```json
{
  "photo_folders": ["D:/your/photo/folder"],
  "default_save_folder": "D:/your/photo/folder",
  "host": "0.0.0.0",
  "port": 8000,
  "thumbnail_modes": {
    "small": { "size": 180, "quality": 58, "queue_limit": 100 },
    "medium": { "size": 300, "quality": 66, "queue_limit": 70 },
    "large": { "size": 520, "quality": 76, "queue_limit": 40 },
    "xlarge": { "size": 1280, "quality": 92, "queue_limit": 30 }
  },
  "memory_prefetch": {
    "enabled": false,
    "memory_limit_mb": 1024
  },
  "theme": "system",
  "upload_password": "",
  "auth": {
    "enabled": false,
    "password": "",
    "session_secret": "",
    "public_albums": [],
    "login_backgrounds": [],
    "login_background_mode": "none",
    "login_background_folder": "",
    "login_background_layout": "grid"
  },
  "plugins": [
    {
      "name": "duplicate_checker",
      "path": "plugins/duplicate_checker/plugin.py"
    },
    {
      "name": "removable_sync",
      "path": "plugins/removable_sync/plugin.py"
    },
    {
      "name": "global_search",
      "path": "plugins/global_search/plugin.py",
      "enabled": false
    },
    {
      "name": "timeline",
      "path": "plugins/timeline/plugin.py",
      "enabled": false
    },
    {
      "name": "recycle_bin",
      "path": "plugins/recycle_bin/plugin.py",
      "enabled": false
    },
    {
      "name": "login_photo_wall",
      "path": "plugins/login_photo_wall/plugin.py",
      "enabled": false
    }
  ]
}
```

### 目录字段

- `photo_folders`：图库根目录列表。
- `default_save_folder`：上传、新建等操作默认保存目录。

`default_save_folder` 不要求位于 `photo_folders` 中。目录不存在时会自动创建；如果它不在任何图库根目录中，会自动作为额外根目录挂载。

### 访问字段

- `host`：监听地址。局域网共享通常使用 `0.0.0.0`。
- `port`：监听端口，默认 `8000`。
- `upload_password`：上传密码。留空表示不限制上传；设置后，新建上传文件夹和上传照片都需要输入正确密码。
- `auth`：访问登录和公开相册配置。

### 缩略图和预取

`thumbnail_modes` 控制不同缩略图模式的尺寸、质量和队列上限：

- `size`：缩略图长边尺寸。
- `quality`：缩略图保存质量。
- `queue_limit`：前端排队上限。

`memory_prefetch.memory_limit_mb` 最小 256MB，最大为系统物理内存减 4GB。查看原图时，core 会尝试预取当前照片前 5 张和后 35 张到共享内存池，多用户共享同一个上限。

## 插件

插件模块需要提供 `register(app, services)` 函数，可选提供 `PLUGIN` manifest。manifest 中的 `components` 用于声明能力、触发点和 UI surface。产品 UI 中统一称为“插件”，schema 文档中保留 `components` 字段名。

启用插件示例：

```json
{
  "plugins": [
    { "name": "duplicate_checker", "path": "plugins/duplicate_checker/plugin.py" },
    { "name": "brackets", "path": "plugins/brackets/plugin.py" }
  ]
}
```

插件模型说明见 [plugin_components.md](plugin_components.md)。

## Windows 平台壳

托盘常驻运行：

```powershell
python .\platform_app\windows\tray_app.py
```

打包 EXE：

```powershell
.\platform_app\windows\build_windows.ps1
```

Windows 壳负责后台启动 core、任务栏右下角常驻图标、右键打开网页、切换“开机自启动”或退出。开机自启动通过托盘菜单里的 `Launch at startup` 开关控制。core 仍可通过 shell app 单独运行。

## Android 平台壳

Android Studio 工程在 [../platform_app/android](../platform_app/android)。当前是传统 Android 工程骨架，后续用于 APK 平台适配和权限处理。

## 数据和缓存

- 评分文件：图库根目录下的 `.photo_share_ratings.json`
- 缩略图、元数据和算法缓存：程序运行目录下的 `.photo_share_cache`
- 删除回收站：程序运行目录下的 `.photo_share_trash`
- 包围曝光合成输出：程序运行目录下的 `.photo_share_bracket_results`
- 平台部署日志：程序运行目录下的 `.deploy`

## 架构边界

- `core/photo_share/` 是唯一后端 core 包，包含服务、业务逻辑、路由、插件加载和共享能力。
- `core/static/` 是 core Web UI。
- `plugins/` 下的功能通过插件 manifest 暴露能力、触发点和 UI surface。
- `platform_app/shell/` 只提供无 GUI 最小启动和部署脚本。
- `platform_app/windows/`、`platform_app/android/` 只处理平台能力和打包适配。

平台壳不承载核心业务；多平台包装都围绕同一个 core 启动和适配。
