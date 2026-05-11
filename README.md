# 局域网照片共享

一个基于 Python + Web 的局域网照片管理与共享 core。它读取 JSON 配置中的本地图库目录，同一局域网内的手机、平板或电脑可以用浏览器访问；Windows / Android 等平台 app 只作为外层壳来启动、承载或打包 core。

## 当前能力

- 浏览多个图库根目录、子文件夹、照片和视频。
- 支持 JPG / JPEG / HEIC / HEIF 图片以及常见视频格式。
- 支持小 / 中 / 大 / 超大缩略图模式，缩略图和元数据缓存在程序运行目录。
- 支持星级评分、日期筛选、缩略图懒加载、原图查看、缩放、旋转、下载和移动到回收站。
- 支持右键/长按菜单、新建文件夹、重命名、删除、复制、移动、文件夹 ZIP 下载和多选 ZIP 下载。
- 支持桌面式多选：Ctrl/Command 点击、Shift 区间选择、鼠标框选、Esc 退出。
- 支持移动端触摸长按菜单和 PWA 基础能力。
- 支持服务端共享内存预取池，适合机械硬盘场景下减少原图读取延迟。
- 支持运行时插件启用/禁用，目前包含重复照片检查、包围曝光检测与合成插件。

## 架构

- `core/photo_share/`：core 后端服务、业务逻辑、路由、插件加载器和共享能力。
- `core/static/`：core Web UI，统一毛玻璃简约风。
- `plugins/`：可选插件。插件通过 manifest 声明能力、触发点和 UI surface。
- `platform_app/shell/`：无 GUI 最小启动入口和部署脚本。
- `platform_app/windows/`：Windows 托盘壳、EXE 打包和开机自启动。
- `platform_app/android/`：Android Studio / APK 平台工程骨架。
- `docs/`：插件模型、编码注意事项和算法说明。

平台壳不应承载核心业务；未来多平台包装都应围绕同一个 core 启动和适配。

## 安装与启动

推荐使用 shell 部署脚本安装依赖并启动 core。

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

本机访问：

```text
http://127.0.0.1:8000
```

局域网其他设备访问：

```text
http://这台电脑的局域网IP:8000
```

## 配置

第一次启动如果没有 `config.json`，程序会创建默认配置并退出。当前配置使用最新格式，不保留旧字段兼容。

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
  "upload_password": "",
  "plugins": [
    {
      "name": "duplicate_checker",
      "path": "plugins/duplicate_checker/plugin.py"
    }
  ]
}
```

`default_save_folder` 不要求位于 `photo_folders` 中。目录不存在时会自动创建；如果它不在任何图库根目录中，会自动作为额外根目录挂载。

`memory_prefetch.memory_limit_mb` 最小 256MB，最大为系统物理内存减 4GB。查看原图时，core 会尝试预取当前照片前 5 张和后 35 张到共享内存池，多用户共享同一个上限。

`upload_password` 留空表示不限制上传；设置为非空字符串后，新建上传文件夹和上传照片都必须输入正确密码。

## 插件

插件模块需要提供 `register(app, services)` 函数，可选提供 `PLUGIN` manifest。manifest 中的 `components` 用于声明能力、触发点和 UI surface。产品 UI 中统一称为“插件”，schema 文档中保留 `components` 字段名。

```json
{
  "plugins": [
    { "name": "duplicate_checker", "path": "plugins/duplicate_checker/plugin.py" },
    { "name": "brackets", "path": "plugins/brackets/plugin.py" }
  ]
}
```

插件模型说明见 [docs/plugin_components.md](docs/plugin_components.md)。

## Windows 平台壳

托盘常驻运行：

```powershell
python .\platform_app\windows\tray_app.py
```

打包 EXE：

```powershell
.\platform_app\windows\build_windows.ps1
```

安装开机自启动：

```powershell
.\platform_app\windows\install_autostart.ps1
```

Windows 壳负责后台启动 core、任务栏右下角常驻图标、右键打开网页或退出。core 仍可通过 shell app 单独运行。

## Android 平台壳

Android Studio 工程在 [platform_app/android](platform_app/android)。当前是稳定传统 Android 工程骨架，后续用于 APK 平台适配和权限处理。

## 数据与缓存

- 评分文件：图库根目录下的 `.photo_share_ratings.json`
- 缩略图/元数据/算法缓存：程序运行目录下的 `.photo_share_cache`
- 删除回收站：程序运行目录下的 `.photo_share_trash`
- 平台部署日志：程序运行目录下的 `.deploy`

## 开发约定

开发前请先阅读 [docs/coding_notes.md](docs/coding_notes.md)。重点约束包括：

- core 和平台壳边界清晰。
- 新配置字段必须同步默认配置、README 和设置页。
- 插件能力通过 manifest 暴露，不在 core 硬编码插件业务。
- UI 统一毛玻璃简约风，危险操作必须使用红色 danger 语义。
- 性能相关改动必须保护缩略图队列、原图缓存和服务端内存预取池。
