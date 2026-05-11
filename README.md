# 局域网照片共享

一个基于 Python + Web 的轻量照片共享工具。启动后读取 JSON 配置中的本地照片文件夹，同一局域网内的手机、平板或电脑可以用浏览器浏览其中的 JPG 图片和子文件夹。

## 功能

- 递归浏览指定文件夹和子文件夹
- 支持 JPG / JPEG 图片
- 后台并行生成缩略图，列表页先显示转圈占位，生成后自动替换
- 缩略图缓存在程序运行目录，不写入照片目录
- 列表只加载可见区域附近的缩略图，减少本地浏览器同时请求数量
- 浏览器内预览原图
- 原图全屏预览，左右透明热区翻页，支持键盘左右键
- 支持按钮缩放、鼠标滚轮缩放、放大后鼠标/触摸拖动、触摸双指缩放
- 平板支持更大的触摸按钮和双指缩放预览
- 支持读取 JPG 已有的 EXIF/XMP 星级作为默认评分
- 支持 OFF 和 1 到 5 星打分，再点同一星级可清除评分
- 支持按星级和照片修改日期筛选
- 支持小 / 中 / 大三档列表预览大小，对应不同缩略图清晰度
- 支持下载原图
- 支持删除图片
- 可选上传密码，密码为空时局域网内可直接上传

## 架构

这个项目分三层：

- `platform_app/shell/`：Linux / Windows shell 场景下的最小启动入口，只启动 core，没有托盘或 GUI
- `core/`：Web 服务、核心逻辑、前端页面和插件加载器
- `platform_app/`：平台壳，负责 Windows EXE / Android APK 这类平台适配

## 安装 Core

推荐使用 `platform_app/shell/deploy` 里的部署脚本自动创建虚拟环境并安装依赖。

Windows PowerShell：

```powershell
.\platform_app\shell\deploy\deploy.ps1 install
```

Linux / macOS：

```bash
chmod +x ./platform_app/shell/deploy/deploy.sh
./platform_app/shell/deploy/deploy.sh install
```

也可以手动安装：

```powershell
D:\codex_prj\photo\.venv\Scripts\python.exe -m ensurepip --upgrade --default-pip
D:\codex_prj\photo\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 启动 Shell App

Windows PowerShell：

```powershell
.\platform_app\shell\deploy\deploy.ps1 init
.\platform_app\shell\deploy\deploy.ps1 start
```

Linux / macOS：

```bash
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

```bash
./platform_app/shell/deploy/deploy.sh start-bg
./platform_app/shell/deploy/deploy.sh status
./platform_app/shell/deploy/deploy.sh logs
./platform_app/shell/deploy/deploy.sh stop
```

`platform_app/shell/app.py` 是最小 shell app 入口，适合服务器、Linux、Windows 控制台和后台脚本调用。它只负责启动 core，不包含托盘图标、窗口或 GUI 壳。

## Windows Platform App

Windows 托盘常驻运行：

```powershell
python .\platform_app\windows\tray_app.py
```

启动后会在任务栏右下角出现常驻图标，右键可打开 Web 界面或退出程序。

### 打包 EXE

Windows:

```powershell
.\platform_app\windows\build_windows.ps1
```

生成文件：

```text
dist\LocalPhotoSharingTray.exe
```

这个 EXE 会：

- 在后台启动本地 Web 服务
- 在任务栏右下角显示常驻小图标
- 右键菜单支持打开网页和退出
- 将运行日志写到程序目录下的 `.deploy\tray-app.log`
- 将配置、缓存、评分等数据写到 EXE 所在目录附近，而不是 PyInstaller 临时目录

安装开机自启动：

```powershell
.\platform_app\windows\install_autostart.ps1
```

这会在当前用户的启动文件夹中创建快捷方式，实现开机后静默启动托盘程序。

Linux 桌面托盘打包预留：

```bash
chmod +x ./platform_app/windows/build_linux.sh
./platform_app/windows/build_linux.sh
```

Linux 版本后续还需要根据目标桌面环境补齐：

- 托盘支持库
- `.desktop` 自启动项
- 可能的 AppImage / 单文件分发方案

指定配置文件：

```powershell
.\platform_app\shell\deploy\deploy.ps1 start -Config D:\photo-share-config.json
```

```bash
./platform_app/shell/deploy/deploy.sh start --config /opt/photo-share/config.json
```

也可以直接用 Python 启动：

```powershell
D:\codex_prj\photo\.venv\Scripts\python.exe platform_app\shell\app.py
```

第一次启动如果没有 `config.json`，程序会自动创建默认配置并退出。编辑 `config.json` 后再次启动即可。

默认配置格式：

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
  "upload_password": "",
  "plugins": [
    {
      "name": "duplicate_checker",
      "path": "plugins/duplicate_checker/plugin.py"
    }
  ]
}
```

`upload_password` 留空表示不限制上传；设置为非空字符串后，新建上传文件夹和上传照片都必须输入正确密码。

`plugins` 用于控制可选功能。默认启用 `duplicate_checker` 重复照片检查插件。平台打包时可以选择把某些插件一起打包，也可以在配置里指定启动哪些插件。

```json
{
  "plugins": []
}
```

例如启用当前仓库里的包围曝光插件：

```json
{
  "plugins": [
    { "name": "brackets", "path": "plugins/brackets/plugin.py" }
  ]
}
```

插件模块需要提供 `register(app, services)` 函数，启动时由 core 加载。
插件还可以在 `PLUGIN["components"]` 中声明组件能力、触发点和页面形态，例如文件夹批处理、后台常驻、文件处理、函数调用、工程文件、弹窗、全局菜单或专属页面。
组件模型说明见 [docs/plugin_components.md](docs/plugin_components.md)。

也可以指定外部插件模块：

```json
{
  "plugins": [
    { "name": "my_plugin", "module": "my_package.my_plugin" }
  ]
}
```

也可以指定配置文件路径：

```powershell
D:\codex_prj\photo\.venv\Scripts\python.exe platform_app\shell\app.py --config D:\photo-share-config.json
```

本机访问：

```text
http://127.0.0.1:8000
```

局域网其他设备访问：

```text
http://这台电脑的局域网IP:8000
```

例如：

```text
http://192.168.1.20:8000
```

## 数据保存

评分保存在共享照片根目录下：

```text
.photo_share_ratings.json
```

缩略图和照片元数据缓存在程序运行目录下：

```text
.photo_share_cache
```

删除操作会直接删除原始 JPG 文件，请只在可信局域网内运行。

## 编码注意事项

见 [docs/coding_notes.md](docs/coding_notes.md)。这些约束用于保护缩略图队列、占位符渲染和大图预下载行为，改动相关代码前先核对。

## Android Platform App

Android Studio 工程在 [platform_app/android](platform_app/android)。之前的 Python APK 试验目录保留在 [platform_app/android/python_demo/README.md](platform_app/android/python_demo/README.md)。

## Project Layout

- `core/photo_share/`：core 后端服务和业务逻辑
- `core/static/`：core 前端页面
- `platform_app/shell/`：最小 shell app 和无 GUI 部署脚本
- `platform_app/windows/`：Windows 托盘壳与 EXE 打包
- `platform_app/android/`：Android APK 平台工程
- `plugins/brackets/`：包围曝光检测与合成插件
- `core/photo_share/plugins.py`：core 插件加载器


![img_1.png](/F:/codex_prj/local-photo-sharing/docs/images/img_1.png)

![img.png](/F:/codex_prj/local-photo-sharing/docs/images/img.png)
