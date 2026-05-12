# 编码注意事项

## 架构边界

- `core/photo_share/` 是唯一后端 core 包，包含服务、业务逻辑、路由、插件加载和共享能力。
- `core/static/` 是 core Web UI。平台壳只能承载或启动 core，不应把平台相关逻辑塞回 core UI。
- `platform_app/shell/` 只提供无 GUI 最小启动和部署脚本。
- `platform_app/windows/`、`platform_app/android/` 只处理平台能力和打包适配。
- `plugins/` 下的功能必须通过插件 manifest 暴露能力、触发点和 UI surface，不要在 core 中硬编码插件业务。

## 配置

- 当前配置使用最新格式，不保留旧字段兼容。新增字段时同步更新 `DEFAULT_CONFIG`、`docs/configuration.md` 和设置页。
- `thumbnail_modes` 同时描述缩略图尺寸、质量和队列上限：`size`、`quality`、`queue_limit`。
- `memory_prefetch.memory_limit_mb` 使用 MB，最小 256MB，最大为系统物理内存减 4GB。
- `default_save_folder` 不要求位于 `photo_folders` 内；不存在时自动创建，不在根目录内时自动作为额外根目录挂载。

## 性能

- 打开文件夹时，前端应为目录内所有媒体和子文件夹创建占位符；缩略图任务由可视区域扫描和 `THUMB_QUEUE_LIMITS` 控制并发与排队。
- 缩略图队列超出上限时，新进入视野的任务应优先挤掉不可见旧任务；如果队列里都是当前可见任务，即使数量超过配置上限也不能丢弃。
- 被挤掉的不可见缩略图任务不应标记失败；对应图片再次进入视野时必须能重新入队加载。
- 浏览器原图缓存按 LRU 淘汰，默认上限为 2GB 或 200 张；退出大图模式只停止当前下载和邻近预下载，不清空已有缓存。
- 服务端内存预取池是多用户共享资源；切换文件夹、关闭查看器或页面卸载时要释放当前用户 lease。

## UI

- core Web UI 统一使用毛玻璃简约风：半透明面板、柔和边框、轻阴影、少量有意义动画。
- 新增弹窗、菜单、设置页和工具条应复用现有视觉语言，不引入突兀的默认浏览器样式。
- 危险操作必须使用 `danger` 语义和红色视觉提示；插件操作应与原生操作分组展示。
