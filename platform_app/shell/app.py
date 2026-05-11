from __future__ import annotations

from core.photo_share.config import (
    parse_args,
    get_config_path,
)
from core.photo_share.server import create_server_runtime


def main() -> None:
    args = parse_args()
    config_path = get_config_path(args.config)
    runtime = create_server_runtime(config_path)
    print(f"Config: {runtime.config_path}")
    print("Sharing:")
    for folder in runtime.folders:
        print(f"  - {folder.resolve()}")
    print(f"Open on this computer: {runtime.local_url}")
    print("Open on LAN devices: http://<this-computer-LAN-IP>:%s" % runtime.port)
    runtime.serve_forever()


if __name__ == "__main__":
    main()
