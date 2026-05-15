# Android Platform App

这是一个本地 Android APK 封装工程。

当前内容：

- 原生 Android `app` 模块
- 本机照片权限申请
- 通过 `MediaStore` 读取本地图片
- 使用原生网格展示本地图库缩略图
- 使用项目 photo gallery 图标作为 APK 桌面图标

建议下一步：

1. 用 Android Studio 打开这个目录
2. 让 IDE 自动同步 Gradle
3. 安装缺失的 Android SDK 组件
4. 运行 `app` 或执行 `gradlew assembleDebug` 生成 APK

如果 Android Studio 提示缺少 Gradle Wrapper，可以直接用 IDE 的同步/修复提示生成。

后续如果要复用 Python `core` 服务能力，可以再评估 Chaquopy 或独立后端同步方案。
