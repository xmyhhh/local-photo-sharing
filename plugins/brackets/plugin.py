from __future__ import annotations

from flask import Flask

from core.photo_share.context import AppServices
from core.photo_share.routes.brackets import register_bracket_routes

PLUGIN = {
    "title": "包围曝光",
    "description": "检测包围曝光序列并创建合成工程。",
    "static_dir": "static",
    "scripts": ["brackets.js"],
    "styles": ["brackets.css"],
    "components": [
        {
            "id": "brackets.detect_folder",
            "title": "包围曝光检测与合成",
            "description": "扫描文件夹中的包围曝光序列，创建可再次打开的包围曝光工程，并批量合成选中的序列。",
            "capabilities": [
                {
                    "type": "folder_batch",
                    "recursive": False,
                    "multi": False,
                    "operations": ["detect_brackets", "merge_selected_groups"],
                },
                {
                    "type": "project",
                    "extension": ".prj",
                    "mime": "application/vnd.local-photo-sharing.bracket-project+json",
                    "operations": ["create_project", "open_project", "save_project"],
                },
            ],
            "triggers": [
                {"type": "context_menu", "target": "folder", "label": "检测包围曝光", "action": "brackets.detect_folder"},
                {"type": "topbar_button", "label": "打开包围曝光项目", "action": "brackets.open_project"},
                {"type": "project_open", "extension": ".prj"},
            ],
            "surfaces": [
                {"type": "dialog", "id": "bracketDialog"},
                {"type": "dedicated_page", "route": "/components/brackets/projects/:path", "status": "planned"},
                {"type": "main_tab", "label": "包围曝光", "status": "planned"},
            ],
        }
    ],
}


def register(app: Flask, services: AppServices) -> None:
    register_bracket_routes(app, services)
