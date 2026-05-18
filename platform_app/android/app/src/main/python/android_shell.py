from __future__ import annotations

import json
import logging
import os
import sys
import traceback
from pathlib import Path
from threading import Lock

_runtime = None
_runtime_lock = Lock()
_log_path = None
_log_stream = None


def start_server(context, app_dir: str, default_photo_dir: str) -> dict:
    global _runtime
    with _runtime_lock:
        if _runtime is not None:
            return _runtime_info(_runtime)

        app_path = Path(app_dir)
        resource_path = Path(__file__).resolve().parent
        photo_path = Path(default_photo_dir)
        app_path.mkdir(parents=True, exist_ok=True)
        photo_path.mkdir(parents=True, exist_ok=True)
        _configure_logging(app_path)
        logging.info("Starting Local Photo Sharing Android service")
        logging.info("App dir: %s", app_path)
        logging.info("Default photo dir: %s", photo_path)

        os.environ["PHOTO_SHARE_APP_DIR"] = str(app_path)
        os.environ["PHOTO_SHARE_RESOURCE_DIR"] = str(resource_path)
        _ensure_import_paths(resource_path)

        from core.photo_share.config import build_default_config, write_config
        from core.photo_share.constants import DEFAULT_CONFIG
        from core.photo_share.server import create_server_runtime

        config_path = app_path / "config.json"
        if not config_path.exists():
            config = build_default_config(photo_path)
            config["host"] = "0.0.0.0"
            config["port"] = 8000
            config["plugins"] = _android_plugin_config(DEFAULT_CONFIG.get("plugins", []))
            write_config(config_path, config)
        else:
            _repair_config(config_path, photo_path)

        try:
            _runtime = create_server_runtime(config_path)
        except Exception:
            logging.exception("Failed to create server runtime")
            raise
        logging.info("Server runtime created on %s:%s", _runtime.host, _runtime.port)
        return _runtime_info(_runtime)


def serve_forever() -> None:
    runtime = _runtime
    if runtime is not None:
        try:
            logging.info("Serving forever")
            runtime.serve_forever()
        except Exception:
            logging.exception("Server loop crashed")
            raise


def stop_server() -> None:
    global _runtime
    with _runtime_lock:
        runtime = _runtime
        _runtime = None
    if runtime is not None:
        logging.info("Stopping server")
        runtime.shutdown()


def status() -> dict:
    runtime = _runtime
    if runtime is None:
        return {"running": False}
    return {"running": True, **_runtime_info(runtime)}


def read_log(max_chars: int = 60000) -> str:
    path = _current_log_path()
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return traceback.format_exc()
    if len(text) > max_chars:
        return text[-max_chars:]
    return text


def clear_log() -> None:
    path = _current_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    logging.info("Log cleared")


def _runtime_info(runtime) -> dict:
    return {
        "host": runtime.host,
        "port": int(runtime.port),
        "local_url": runtime.local_url,
        "folders": [str(item) for item in runtime.folders],
    }


def _ensure_import_paths(resource_path: Path) -> None:
    for candidate in (resource_path,):
        text = str(candidate)
        if text not in sys.path:
            sys.path.insert(0, text)


def _configure_logging(app_path: Path) -> None:
    global _log_path, _log_stream
    _log_path = app_path / "android_service.log"
    _log_path.parent.mkdir(parents=True, exist_ok=True)
    if _log_stream is None:
        _log_stream = _log_path.open("a", encoding="utf-8", buffering=1)
    sys.stdout = _log_stream
    sys.stderr = _log_stream
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
    file_handler = logging.StreamHandler(_log_stream)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
    logging.getLogger("werkzeug").setLevel(logging.INFO)


def _current_log_path() -> Path:
    if _log_path is not None:
        return _log_path
    app_dir = os.environ.get("PHOTO_SHARE_APP_DIR")
    if app_dir:
        return Path(app_dir) / "android_service.log"
    return Path("android_service.log")


def _repair_config(config_path: Path, default_photo_dir: Path) -> None:
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(config, dict):
        return
    changed = False
    folders = config.get("photo_folders")
    if not isinstance(folders, list) or not folders:
        config["photo_folders"] = [str(default_photo_dir)]
        changed = True
    if not isinstance(config.get("default_save_folder"), str) or not config["default_save_folder"].strip():
        config["default_save_folder"] = str(default_photo_dir)
        changed = True
    if config.get("host") != "0.0.0.0":
        config["host"] = "0.0.0.0"
        changed = True
    if changed:
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def _android_plugin_config(plugins: list) -> list:
    patched = []
    for item in plugins:
        if not isinstance(item, dict):
            patched.append(item)
            continue
        next_item = dict(item)
        if next_item.get("name") == "cloud_backup":
            next_item["enabled"] = False
        elif next_item.get("enabled") is False:
            next_item["enabled"] = True
        patched.append(next_item)
    return patched
