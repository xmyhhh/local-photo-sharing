from __future__ import annotations

from time import time
from typing import Any

from flask import Flask, jsonify

from ..auth import require_admin
from ..context import AppServices


ACTIVE_STATES = {"queued", "running", "scanning", "indexing", "error"}


def register_task_routes(app: Flask, services: AppServices) -> None:
    @app.get("/api/tasks")
    def backend_tasks():
        require_admin(services)
        tasks = collect_backend_tasks(services)
        active = sum(1 for task in tasks if task.get("state") in {"queued", "running", "scanning", "indexing"})
        errors = sum(1 for task in tasks if task.get("state") == "error")
        return jsonify({
            "tasks": tasks,
            "active": active,
            "errors": errors,
            "updatedAt": int(time()),
        })


def collect_backend_tasks(services: AppServices) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    tasks.extend(core_task_snapshots(services))
    tasks.extend(plugin_task_snapshots(services))
    return [task for task in tasks if task.get("state") in ACTIVE_STATES]


def core_task_snapshots(services: AppServices) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    warmup = services.warmup_status
    if warmup is not None:
        snapshot = warmup.snapshot()
        if snapshot.get("state") in ACTIVE_STATES:
            tasks.append(normalize_task({
                "id": "core.thumbnail_warmup",
                "source": "core",
                "title": "缩略图预热",
                "detail": snapshot.get("stage", ""),
                "state": snapshot.get("state"),
                "progress": snapshot.get("progress"),
                "completed": snapshot.get("completed"),
                "total": snapshot.get("total"),
                "error": snapshot.get("error", ""),
                "meta": {
                    "generated": snapshot.get("generated", 0),
                    "failed": snapshot.get("failed", 0),
                    "workers": snapshot.get("workers", 0),
                },
            }))

    for root_id, root_services in services.root_services.items():
        folder_counts = root_services.folder_counts
        with folder_counts.lock:
            if folder_counts.inflight:
                tasks.append(normalize_task({
                    "id": f"core.folder_counts.{root_id}",
                    "source": "core",
                    "title": f"目录计数索引 {root_id}",
                    "detail": str(root_services.root),
                    "state": "scanning",
                    "completed": folder_counts.scanned_entries,
                    "total": None,
                    "progress": None,
                }))
            for rel in sorted(folder_counts.refreshing):
                tasks.append(normalize_task({
                    "id": f"core.folder_counts.{root_id}.{rel}",
                    "source": "core",
                    "title": f"刷新目录计数 {root_id}",
                    "detail": rel or "/",
                    "state": "running",
                    "progress": None,
                }))

        queued = 0
        inflight = 0
        errors = 0
        modes: list[str] = []
        for mode, store in root_services.thumbnails.items():
            with store.lock:
                mode_queued = len(store.queued) + len(store.queue)
                mode_inflight = len(store.inflight)
                mode_errors = len(store.errors)
            if mode_queued or mode_inflight or mode_errors:
                modes.append(mode)
            queued += mode_queued
            inflight += mode_inflight
            errors += mode_errors
        if queued or inflight or errors:
            state = "error" if errors and not (queued or inflight) else "running"
            tasks.append(normalize_task({
                "id": f"core.thumbnail_queue.{root_id}",
                "source": "core",
                "title": f"缩略图生成 {root_id}",
                "detail": str(root_services.root),
                "state": state,
                "completed": inflight,
                "total": queued + inflight,
                "progress": None,
                "error": f"{errors} 个缩略图生成失败" if errors else "",
                "meta": {
                    "queued": queued,
                    "inflight": inflight,
                    "errors": errors,
                    "modes": modes,
                },
            }))

    tasks.extend(bracket_task_snapshots(services))
    return tasks


def bracket_task_snapshots(services: AppServices) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for task_id, task in services.bracket_tasks.items():
        status = dict(task.get("status") or {})
        if status.get("state") not in ACTIVE_STATES:
            continue
        tasks.append(normalize_task({
            "id": f"core.bracket_detection.{task_id}",
            "source": "core",
            "title": "包围曝光检测",
            "detail": status.get("folder") or "/",
            "state": status.get("state"),
            "progress": status.get("progress"),
            "completed": status.get("processed"),
            "total": status.get("total"),
            "error": status.get("message", ""),
            "meta": {
                "groups": status.get("count", 0),
                "root": status.get("root", ""),
                "etaSeconds": status.get("etaSeconds"),
            },
        }))
    for task_id, task in services.bracket_merge_tasks.items():
        status = dict(task.get("status") or {})
        if status.get("state") not in ACTIVE_STATES:
            continue
        tasks.append(normalize_task({
            "id": f"core.bracket_merge.{task_id}",
            "source": "core",
            "title": "包围曝光合成",
            "detail": status.get("stage", ""),
            "state": status.get("state"),
            "progress": status.get("progress"),
            "completed": status.get("processed"),
            "total": status.get("total"),
            "error": status.get("message", ""),
        }))
    return tasks


def plugin_task_snapshots(services: AppServices) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for name in sorted(services.enabled_plugins):
        module = services.plugin_modules.get(name)
        collector = getattr(module, "get_backend_tasks", None)
        if not callable(collector):
            continue
        try:
            raw_tasks = collector(services)
        except Exception as exc:  # noqa: BLE001 - task panel must not break app.
            raw_tasks = [{
                "id": f"{name}.task_status",
                "source": name,
                "title": f"{name} 任务状态",
                "state": "error",
                "error": str(exc),
            }]
        if not isinstance(raw_tasks, list):
            continue
        for raw in raw_tasks:
            if isinstance(raw, dict):
                task = normalize_task(raw, fallback_source=name)
                task["id"] = f"plugin.{name}.{task['id']}"
                tasks.append(task)
    return tasks


def normalize_task(raw: dict[str, Any], fallback_source: str = "core") -> dict[str, Any]:
    state = str(raw.get("state") or "running")
    progress = raw.get("progress")
    try:
        progress_value = None if progress is None else max(0.0, min(1.0, float(progress)))
    except (TypeError, ValueError):
        progress_value = None
    return {
        "id": str(raw.get("id") or raw.get("title") or "task"),
        "source": str(raw.get("source") or fallback_source),
        "title": str(raw.get("title") or "后台任务"),
        "detail": str(raw.get("detail") or raw.get("stage") or ""),
        "state": state,
        "progress": progress_value,
        "completed": raw.get("completed"),
        "total": raw.get("total"),
        "error": str(raw.get("error") or raw.get("message") or ""),
        "meta": raw.get("meta") if isinstance(raw.get("meta"), dict) else {},
    }
