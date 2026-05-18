# Flet 配置器原型

这是一个独立的本机配置界面原型，用 Flet 编写。它不会替换现有 Windows 托盘程序，先用于验证“跨平台配置界面 + Python Core”的路线。

## 运行

```powershell
.\.venv\Scripts\python.exe -m pip install -r platform_app\config_ui_flet\requirements.txt
.\.venv\Scripts\python.exe platform_app\config_ui_flet\app.py
```

可选参数：

```powershell
.\.venv\Scripts\python.exe platform_app\config_ui_flet\app.py --config D:\photo-share-config.json --start-service
```

## 当前能力

- 照片库管理：管理多个照片库目录，设置默认上传目录
- 网络 / 端口：修改本地 Web 服务监听地址和端口
- 日志 / 诊断：查看本机日志尾部、打开日志目录、复制诊断信息
- 保存 `config.json`
- 启动、停止、重启本地 Python Web 服务
- 打开本机 Web UI

Windows 托盘程序会从右键菜单“打开本机设置...”启动这个配置器。通过托盘打开时，服务仍由托盘进程负责，配置器关闭后托盘进程会重启服务让配置生效。

## 后续验证点

- Windows `flet build windows`
- Linux `flet build linux`
- Android 需要单独验证存储权限、后台服务和目录 URI 模型
