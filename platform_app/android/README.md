# Android Platform App

这是 Local Photo Sharing 的 Android 壳子。它不做原生图库 UI，也不把 WebView 当主界面；APK 负责启动打包在应用内的 Python `core` 服务，并把本机地址、局域网地址显示出来，供同一 Wi-Fi / 局域网里的其他设备访问。

## 内容

- Android 原生控制面板
- Foreground service 持有 Python 服务进程
- Chaquopy 打包 `core/` 和 `plugins/`
- APK 图标使用 `core/assets/icons8-photo-gallery-96.png`
- 适配状态栏、导航栏和挖孔屏安全区域

## 默认目录

首次启动服务时会在应用私有数据目录创建 `photo_share/config.json`。默认照片目录是应用外部私有 Pictures 目录：

```text
Android/data/org.example.localphotoandroid/files/Pictures
```

这个目录不需要额外授权，适合作为 Android APK 初始可写照片库。后续如果要直接分享系统相册/DCIM，可以在配置里把 `photo_folders` 改成设备可访问的路径，并按 Android 版本处理媒体权限或存储访问授权。

## 编译

用 Android Studio 打开 `platform_app/android` 后同步 Gradle，选择一个 Python flavor 编译：

```text
py311Debug
```

也可以用命令行：

```powershell
.\gradlew.bat :app:assemblePy311Debug
```

如果本机 Python/Chaquopy 环境更适合 3.10 或 3.12，可以切到 `py310Debug` 或 `py312Debug`。
