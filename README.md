# 局域网照片共享

一个给家里或工作室局域网用的照片管理与共享工具。电脑负责读取本地图库，手机、平板和其他电脑用浏览器访问。

主体是 Python 后端和 Web 界面；Windows、Android 目录用于启动、打包或接入系统能力。

## 主要功能

- 浏览多个图库目录，查看照片、视频和子文件夹。
- 支持 JPG / JPEG / PNG / HEIC / HEIF / HDR 图片和常见视频格式。
- 提供缩略图、原图查看、缩放、旋转、下载、评分、日期筛选和移动到回收站。
- 支持新建文件夹、重命名、删除、复制、移动、文件夹 ZIP 下载和多选 ZIP 下载。
- 支持桌面多选、移动端长按菜单和 PWA 基础能力。
- 支持插件扩展，当前包括重复照片检查、包围曝光检测/合成、移动设备同步、全局搜索、时间线、回收站和登录照片墙等能力。

## 快速开始

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

第一次启动会生成 `config.json`。把里面的 `photo_folders` 和 `default_save_folder` 改成你的照片目录后，再启动服务。

访问地址：

```text
http://127.0.0.1:8000
```

局域网其他设备访问：

```text
http://这台电脑的局域网IP:8000
```

## 常用命令

```powershell
.\platform_app\shell\deploy\deploy.ps1 start-bg
.\platform_app\shell\deploy\deploy.ps1 status
.\platform_app\shell\deploy\deploy.ps1 logs
.\platform_app\shell\deploy\deploy.ps1 stop
```

直接启动服务：

```powershell
.\.venv\Scripts\python.exe platform_app\shell\app.py
```

指定配置文件：

```powershell
.\.venv\Scripts\python.exe platform_app\shell\app.py --config D:\photo-share-config.json
```

预生成缩略图缓存：

```powershell
.\.venv\Scripts\python.exe platform_app\shell\app.py warmup
```

## 项目结构

- `core/`：后端服务、Web UI、路由、缓存和共享能力。
- `plugins/`：可选插件。
- `platform_app/shell/`：无 GUI 启动入口和部署脚本。
- `platform_app/windows/`：Windows 托盘壳和 EXE 打包。
- `platform_app/android/`：Android 平台工程。
- `docs/`：配置、平台、插件、开发约定和算法说明。

## 文档

- [运行与配置](docs/configuration.md)
- [插件模型](docs/plugin_components.md)
- [开发注意事项](docs/coding_notes.md)
- [包围曝光合成算法说明](docs/bracket_merge_rgb_math.md)
