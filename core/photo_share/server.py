from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from werkzeug.serving import BaseWSGIServer, make_server

from .config import (
    get_host,
    get_default_save_folder,
    get_photo_folders,
    get_port,
    get_preview_quality,
    get_preview_size,
    get_thumbnail_mode_settings,
    get_thumbnail_queue_limits,
    get_upload_password,
    load_config,
)
from .factory import create_app
from .plugins import discover_plugin_specs


@dataclass(slots=True)
class ServerRuntime:
    config_path: Path
    host: str
    port: int
    folders: list[Path]
    server: BaseWSGIServer

    @property
    def local_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def serve_forever(self) -> None:
        self.server.serve_forever()

    def shutdown(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def create_server_runtime(config_path: Path) -> ServerRuntime:
    config = load_config(config_path)
    if config is None:
        raise SystemExit(0)

    folders = get_photo_folders(config)
    host = get_host(config)
    port = get_port(config)
    app = create_app(
        folders,
        preview_size=get_preview_size(config),
        preview_quality=get_preview_quality(config),
        thumbnail_queue_limits=get_thumbnail_queue_limits(config),
        thumbnail_mode_settings=get_thumbnail_mode_settings(config),
        upload_password=get_upload_password(config),
        plugin_specs=discover_plugin_specs(config),
        config=config,
        config_path=config_path,
        default_save_folder=get_default_save_folder(config),
    )
    server = make_server(host, port, app, threaded=True)
    return ServerRuntime(
        config_path=config_path,
        host=host,
        port=port,
        folders=folders,
        server=server,
    )
