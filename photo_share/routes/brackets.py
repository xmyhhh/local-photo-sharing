from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from time import perf_counter
from uuid import uuid4

from flask import Flask, jsonify, request

from ..brackets import detect_exposure_brackets
from ..context import AppServices
from ..paths import resolve_folder

BRACKET_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="bracket-detection")
BRACKET_TASK_LOCK = Lock()


def register_bracket_routes(app: Flask, services: AppServices) -> None:
    @app.get("/api/bracket-detection")
    def bracket_detection():
        if not hasattr(services, "bracket_tasks"):
            services.bracket_tasks = {}
        folder = request.args.get("folder", "")
        folder_path = resolve_folder(services.root, folder)
        task_id = request.args.get("task_id")
        if task_id:
            task = services.bracket_tasks.get(task_id)
            if not task:
                return jsonify({"error": "task not found"}), 404
            return jsonify({"folder": folder, **task["status"]})
        with BRACKET_TASK_LOCK:
            cleanup_bracket_tasks(services)
            existing = find_active_task_for_folder(services, folder)
            if existing is not None:
                return jsonify({"taskId": existing["status"]["taskId"], **existing["status"]}), 202
        task_id = uuid4().hex
        services.bracket_tasks[task_id] = {
            "status": {
                "taskId": task_id,
                "folder": folder,
                "state": "queued",
                "progress": 0.0,
                "groups": [],
                "processed": 0,
                "total": 0,
                "elapsedSeconds": None,
                "etaSeconds": None,
                "count": 0,
            }
        }
        future = BRACKET_EXECUTOR.submit(run_bracket_detection_task, services, folder, folder_path, task_id)
        services.bracket_tasks[task_id]["future"] = future
        return jsonify({"taskId": task_id, "state": "queued"}), 202


def run_bracket_detection_task(services: AppServices, folder: str, folder_path, task_id: str) -> None:
    started_at = perf_counter()
    with BRACKET_TASK_LOCK:
        task = services.bracket_tasks.get(task_id)
        if task:
            task["status"].update(
                {
                    "taskId": task_id,
                    "folder": folder,
                    "state": "running",
                    "progress": 0.0,
                    "processed": 0,
                    "total": 0,
                    "elapsedSeconds": 0.0,
                    "etaSeconds": None,
                    "count": 0,
                }
            )

    def progress_callback(processed: int, total: int, groups_count: int) -> None:
        elapsed = perf_counter() - started_at
        progress = 1.0 if total <= 0 else processed / total
        eta = None
        if processed > 0 and total > processed:
            per_item = elapsed / processed
            eta = per_item * (total - processed)
        with BRACKET_TASK_LOCK:
            task = services.bracket_tasks.get(task_id)
            if not task:
                return
            task["status"].update(
                {
                    "taskId": task_id,
                    "state": "running",
                    "progress": round(progress, 6),
                    "processed": processed,
                    "total": total,
                    "count": groups_count,
                    "elapsedSeconds": round(elapsed, 3),
                    "etaSeconds": round(eta, 3) if eta is not None else None,
                }
            )

    try:
        result = detect_exposure_brackets(
            services.root,
            folder_path,
            services.default_thumbnails,
            scan_limit=None,
            progress_callback=progress_callback,
        )
        elapsed = perf_counter() - started_at
        with BRACKET_TASK_LOCK:
            task = services.bracket_tasks.get(task_id)
            if task:
                task["status"] = {
                    "taskId": task_id,
                    "state": "done",
                    "folder": folder,
                    "progress": 1.0,
                    "processed": result["processed"],
                    "total": result["total"],
                    "elapsedSeconds": round(elapsed, 3),
                    "etaSeconds": 0.0,
                    **result,
                }
    except Exception as error:
        with BRACKET_TASK_LOCK:
            task = services.bracket_tasks.get(task_id)
            if task:
                task["status"] = {
                    "taskId": task_id,
                    "state": "error",
                    "folder": folder,
                    "message": str(error),
                }


def find_active_task_for_folder(services: AppServices, folder: str) -> dict | None:
    for task in services.bracket_tasks.values():
        status = task.get("status", {})
        if status.get("folder") != folder:
            continue
        if status.get("state") in {"queued", "running"}:
            return task
    return None


def cleanup_bracket_tasks(services: AppServices, keep: int = 20) -> None:
    completed = [
        (task_id, task)
        for task_id, task in services.bracket_tasks.items()
        if task.get("status", {}).get("state") in {"done", "error"}
    ]
    if len(completed) <= keep:
        return
    completed.sort(key=lambda item: item[0])
    for task_id, _task in completed[:-keep]:
        services.bracket_tasks.pop(task_id, None)
