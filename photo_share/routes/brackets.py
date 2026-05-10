from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock
from time import perf_counter
from uuid import uuid4

from flask import Flask, jsonify, request

from ..brackets import detect_exposure_brackets
from ..context import AppServices
from ..paths import resolve_folder

BRACKET_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bracket-detection")
BRACKET_TASK_LOCK = Lock()


def register_bracket_routes(app: Flask, services: AppServices) -> None:
    @app.get("/api/bracket-detection")
    def bracket_detection():
        folder = request.args.get("folder", "")
        folder_path = resolve_folder(services.root, folder)
        task_id = request.args.get("task_id")
        if task_id:
            task = services.bracket_tasks.get(task_id)
            if not task:
                return jsonify({"error": "task not found"}), 404
            return jsonify({"folder": folder, **task["status"]})
        task_id = uuid4().hex
        services.bracket_tasks[task_id] = {"status": {"taskId": task_id, "state": "queued", "progress": 0.0, "groups": [], "elapsedSeconds": 0.0, "etaSeconds": None, "count": 0}}
        future = BRACKET_EXECUTOR.submit(run_bracket_detection_task, services, folder, folder_path, task_id)
        services.bracket_tasks[task_id]["future"] = future
        return jsonify({"taskId": task_id, "state": "queued"}), 202


def run_bracket_detection_task(services: AppServices, folder: str, folder_path, task_id: str) -> None:
    started_at = perf_counter()

    def progress_callback(processed: int, total: int) -> None:
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
