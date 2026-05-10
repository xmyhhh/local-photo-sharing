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

## 安装

推荐使用部署脚本自动创建虚拟环境并安装依赖。

Windows PowerShell：

```powershell
.\deploy.ps1 install
```

Linux / macOS：

```bash
chmod +x ./deploy.sh
./deploy.sh install
```

也可以手动安装：

```powershell
D:\codex_prj\photo\.venv\Scripts\python.exe -m ensurepip --upgrade --default-pip
D:\codex_prj\photo\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 启动

Windows PowerShell：

```powershell
.\deploy.ps1 init
.\deploy.ps1 start
```

Linux / macOS：

```bash
./deploy.sh init
./deploy.sh start
```

后台运行：

```powershell
.\deploy.ps1 start-bg
.\deploy.ps1 status
.\deploy.ps1 logs
.\deploy.ps1 stop
```

```bash
./deploy.sh start-bg
./deploy.sh status
./deploy.sh logs
./deploy.sh stop
```

指定配置文件：

```powershell
.\deploy.ps1 start -Config D:\photo-share-config.json
```

```bash
./deploy.sh start --config /opt/photo-share/config.json
```

也可以直接用 Python 启动：

```powershell
D:\codex_prj\photo\.venv\Scripts\python.exe app.py
```

第一次启动如果没有 `config.json`，程序会自动创建默认配置并退出。编辑 `config.json` 后再次启动即可。

默认配置格式：

```json
{
  "photo_folder": "D:/your/photo/folder",
  "host": "0.0.0.0",
  "port": 8000,
  "thumbnail_size": 360,
  "thumbnail_quality": 74,
  "preview_size": 2560,
  "preview_quality": 88,
  "upload_password": ""
}
```

`upload_password` 留空表示不限制上传；设置为非空字符串后，新建上传文件夹和上传照片都必须输入正确密码。

也可以指定配置文件路径：

```powershell
D:\codex_prj\photo\.venv\Scripts\python.exe app.py --config D:\photo-share-config.json
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

- `thumbnail_queue_limits` 只表示各缩略图模式下的缩略图加载/生成任务队列上限。它不是列表分页大小，也不是 DOM 占位符数量上限。
- 打开文件夹时，前端应为目录内所有媒体和子文件夹创建占位符；缩略图任务再由可视区域扫描和 `THUMB_QUEUE_LIMITS` 控制并发与排队。
- 缩略图队列超出上限时，新进入视野的任务应优先挤掉不可见的旧任务；如果队列里都是当前可见任务，即使数量超过配置上限也不能丢弃它们。
- 被挤掉的不可见缩略图任务不应标记失败；对应图片再次进入视野时必须能重新入队加载。
- 大图查看器应在非快速连翻状态下预下载当前照片前 3 张和后 3 张原图；快速连翻时暂停邻近原图预下载，停止后再恢复。


![img_1.png](img_1.png)

![img.png](img.png)
