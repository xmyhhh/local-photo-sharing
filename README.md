# 局域网照片共享

一个基于 Python + Web 的轻量照片共享工具。启动后指定本地照片文件夹，同一局域网内的手机、平板或电脑可以用浏览器浏览其中的 JPG 图片和子文件夹。

## 功能

- 递归浏览指定文件夹和子文件夹
- 支持 JPG / JPEG 图片
- 自动生成缩略图
- 浏览器内预览原图
- 支持按钮缩放和 `Ctrl + 鼠标滚轮` 缩放
- 支持 1 到 5 星打分，再点同一星级可清除评分
- 支持删除图片
- 无登录、无密码，适合可信局域网使用

## 安装

```powershell
D:\codex_prj\photo\.venv\Scripts\python.exe -m ensurepip --upgrade --default-pip
D:\codex_prj\photo\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 启动

```powershell
D:\codex_prj\photo\.venv\Scripts\python.exe app.py "D:\你的照片文件夹" --host 0.0.0.0 --port 8000
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

缩略图缓存在共享照片根目录下：

```text
.photo_share_thumbs
```

删除操作会直接删除原始 JPG 文件，请只在可信局域网内运行。
