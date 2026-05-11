from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .constants import DEFAULT_BRACKET_PROJECT_FILE

BRACKET_PROJECT_VERSION = 1


def default_project_path() -> Path:
    return DEFAULT_BRACKET_PROJECT_FILE


def load_bracket_project(path: Path | None = None) -> dict[str, Any]:
    project_path = (path or default_project_path()).resolve()
    try:
        data = json.loads(project_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(str(project_path)) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read bracket project: {project_path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Invalid bracket project: {project_path}")
    return data


def save_bracket_project(project: dict[str, Any], path: Path | None = None) -> Path:
    project_path = (path or default_project_path()).resolve()
    project_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": BRACKET_PROJECT_VERSION,
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
        **project,
    }
    project_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return project_path


def build_project(
    root_id: str,
    folder: str,
    detection: dict[str, Any],
    params: dict[str, Any] | None = None,
    selected_group_ids: list[int] | None = None,
    merge_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    groups = detection.get("groups", [])
    selected = selected_group_ids if selected_group_ids is not None else [int(group["id"]) for group in groups]
    return {
        "type": "photo-share-bracket-project",
        "root": root_id,
        "folder": folder,
        "detection": detection,
        "selectedGroupIds": selected,
        "params": params or default_merge_params(),
        "mergeResult": merge_result,
    }


def default_merge_params() -> dict[str, str]:
    return {
        "algorithm": "fusion",
        "alignment": "people",
        "exposure": "0",
        "shadows": "0.25",
        "highlights": "0.15",
        "contrast": "1",
        "saturation": "1",
        "sharpen": "0.2",
        "quality": "92",
    }
