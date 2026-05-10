from __future__ import annotations

from photo_share.config import (
    get_config_path,
    get_host,
    get_photo_folders,
    get_port,
    get_preview_quality,
    get_preview_size,
    get_thumbnail_queue_limits,
    get_thumbnail_quality,
    get_thumbnail_size,
    get_upload_password,
    load_config,
    parse_args,
)
from photo_share.factory import create_app


def main() -> None:
    args = parse_args()
    config_path = get_config_path(args.config)
    config = load_config(config_path)
    if config is None:
        raise SystemExit(0)

    folders = get_photo_folders(config)
    host = get_host(config)
    port = get_port(config)
    app = create_app(
        folders,
        thumbnail_size=get_thumbnail_size(config),
        thumbnail_quality=get_thumbnail_quality(config),
        preview_size=get_preview_size(config),
        preview_quality=get_preview_quality(config),
        thumbnail_queue_limits=get_thumbnail_queue_limits(config),
        upload_password=get_upload_password(config),
    )
    print(f"Config: {config_path}")
    print("Sharing:")
    for folder in folders:
        print(f"  - {folder.resolve()}")
    print(f"Open on this computer: http://127.0.0.1:{port}")
    print("Open on LAN devices: http://<this-computer-LAN-IP>:%s" % port)
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
