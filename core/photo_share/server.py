from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from werkzeug.serving import BaseWSGIServer, make_server

from .config import (
    get_host,
    get_default_save_folder,
    get_photo_folders,
    get_port,
    get_memory_prefetch_settings,
    get_thumbnail_mode_settings,
    get_upload_password,
    load_config,
)
from .factory import create_app
from .plugins import discover_plugin_specs
from .warmup import warmup_thumbnail_caches


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


def create_server_runtime(config_path: Path, warmup: bool = False) -> ServerRuntime:
    config = load_config(config_path)
    if config is None:
        raise SystemExit(0)

    folders = get_photo_folders(config)
    host = get_host(config)
    port = get_port(config)
    app = create_app(
        folders,
        thumbnail_mode_settings=get_thumbnail_mode_settings(config),
        memory_prefetch_settings=get_memory_prefetch_settings(config),
        upload_password=get_upload_password(config),
        plugin_specs=discover_plugin_specs(config),
        config=config,
        config_path=config_path,
        default_save_folder=get_default_save_folder(config),
    )
    if warmup:
        warmup_thumbnail_caches(app.config["photo_share_services"])
    server = make_server(host, port, app, threaded=True)
    return ServerRuntime(
        config_path=config_path,
        host=host,
        port=port,
        folders=folders,
        server=server,
    )
