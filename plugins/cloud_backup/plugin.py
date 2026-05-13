from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from flask import Flask, abort, jsonify, request

from core.photo_share.auth import require_admin
from core.photo_share.context import AppServices

PLUGIN_DIR = Path(__file__).resolve().parent
PLUGIN_PARENT = PLUGIN_DIR.parent
if str(PLUGIN_PARENT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_PARENT))

from cloud_backup.engine import PLUGIN_NAME, CloudBackupEngine

ENGINE = CloudBackupEngine()

PLUGIN = {
    "title": "冷备份",
    "description": "定期把图库增量备份到本地目录，后续可扩展到阿里云盘和 123 云盘。",
    "static_dir": "static",
    "scripts": ["cloud_backup.js"],
    "styles": ["cloud_backup.css"],
    "components": [
        {
            "id": "cloud_backup.settings",
            "title": "冷备份",
            "description": "按备份清单增量上传媒体文件，第一阶段支持本地目录目标。",
            "capabilities": [
                {"type": "background_service", "operations": ["scan", "incremental_backup", "schedule"]},
                {"type": "cloud_backup", "providers": ["local_folder", "aliyundrive", "pan123"]},
            ],
            "triggers": [],
            "surfaces": [
                {
                    "type": "settings_page",
                    "id": "cloud_backup.settings",
                    "label": "冷备份",
                    "title": "冷备份",
                    "kicker": "备份",
                    "description": "把图库定期复制到独立备份位置，先从本地目录开始。",
                }
            ],
        }
    ],
}


def register(app: Flask, services: AppServices) -> None:
    @app.get("/api/cloud-backup/settings")
    def cloud_backup_settings():
        require_admin(services)
        if PLUGIN_NAME not in services.enabled_plugins:
            abort(404)
        return jsonify(ENGINE.settings_payload())

    @app.post("/api/cloud-backup/settings")
    def update_cloud_backup_settings():
        require_admin(services)
        if PLUGIN_NAME not in services.enabled_plugins:
            abort(404)
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            abort(400, "settings must be an object.")
        return jsonify(ENGINE.update_settings(data))

    @app.post("/api/cloud-backup/run")
    def run_cloud_backup():
        require_admin(services)
        if PLUGIN_NAME not in services.enabled_plugins:
            abort(404)
        return jsonify(ENGINE.run_now())

    @app.get("/api/cloud-backup/status")
    def cloud_backup_status():
        require_admin(services)
        if PLUGIN_NAME not in services.enabled_plugins:
            abort(404)
        return jsonify(ENGINE.status())


def on_enable(services: AppServices) -> None:
    ENGINE.start(services)


def on_disable(services: AppServices) -> None:
    ENGINE.stop()


def get_backend_tasks(services: AppServices) -> list[dict[str, Any]]:
    return ENGINE.get_backend_tasks()
