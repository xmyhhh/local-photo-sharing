from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from time import perf_counter
from uuid import uuid4

from flask import Flask, abort, jsonify, request

from ..bracket_merge import merge_bracket_groups, resolve_merge_output
from ..brackets import detect_exposure_brackets
from ..constants import BRACKET_CACHE_FILE
from ..context import AppServices
from ..paths import join_rooted_path, quote_path, send_cached_file
from .gallery import _resolve_rooted_folder, _root_services

BRACKET_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="bracket-detection")
BRACKET_MERGE_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bracket-merge")
BRACKET_TASK_LOCK = Lock()


def register_bracket_routes(app: Flask, services: AppServices) -> None:
    @app.get("/api/bracket-detection")
    def bracket_detection():
        ensure_bracket_cache_loaded(services)
        root_id = request.args.get("root", services.default_root_id)
        folder = normalize_bracket_folder(root_id, request.args.get("folder", ""))
        task_id = request.args.get("task_id")
        if task_id:
            task = services.bracket_tasks.get(task_id)
            if not task:
                return jsonify({"error": "task not found"}), 404
            return jsonify({"root": root_id, "folder": folder, **task["status"]})

        cache_key = bracket_cache_key(root_id, folder)
        force = request.args.get("force") == "1"
        cached = services.bracket_cache.get(cache_key)
        if cached and not force:
            return jsonify({"root": root_id, "folder": folder, "state": "cached", "hasCached": True, **cached})

        folder_path = _resolve_rooted_folder(services, root_id, folder)
        root_services = _root_services(services, root_id)
        with BRACKET_TASK_LOCK:
            cleanup_bracket_tasks(services)
            existing = find_active_task_for_folder(services, root_id, folder)
            if existing is not None:
                return jsonify({"taskId": existing["status"]["taskId"], **existing["status"]}), 202

        task_id = uuid4().hex
        services.bracket_tasks[task_id] = {"status": initial_task_status(task_id, root_id, folder)}
        future = BRACKET_EXECUTOR.submit(
            run_bracket_detection_task,
            services,
            root_id,
            folder,
            folder_path,
            root_services.default_thumbnails,
            task_id,
        )
        services.bracket_tasks[task_id]["future"] = future
        return jsonify({"taskId": task_id, "root": root_id, "folder": folder, "state": "queued"}), 202

    @app.post("/api/bracket-merge")
    def bracket_merge():
        ensure_bracket_cache_loaded(services)
        data = request.get_json(silent=True) or {}
        task_id = data.get("taskId")
        if task_id:
            task = services.bracket_merge_tasks.get(task_id)
            if not task:
                return jsonify({"error": "task not found"}), 404
            return jsonify(task["status"])

        root_id = data.get("root") or services.default_root_id
        folder = normalize_bracket_folder(root_id, data.get("folder") or "")
        group_ids = data.get("groupIds") or []
        if not isinstance(group_ids, list):
            abort(400, "groupIds must be a list.")
        cache_key = bracket_cache_key(root_id, folder)
        cached = services.bracket_cache.get(cache_key)
        if not cached and isinstance(data.get("groups"), list):
            cached = root_bracket_result({"groups": data["groups"]}, root_id)
            services.bracket_cache[cache_key] = cached
            save_bracket_cache(services)
        if not cached:
            abort(409, "No cached bracket detection result for this folder.")
        task_id = uuid4().hex
        group_ids_int = [int(group_id) for group_id in group_ids]
        services.bracket_merge_tasks[task_id] = {
            "status": {
                "taskId": task_id,
                "state": "queued",
                "progress": 0.0,
                "stage": "等待合成",
                "processed": 0,
                "total": len(group_ids_int),
                "result": None,
            }
        }
        future = BRACKET_MERGE_EXECUTOR.submit(
            run_bracket_merge_task,
            services,
            task_id,
            root_id,
            cached,
            group_ids_int,
            data.get("params") or {},
        )
        services.bracket_merge_tasks[task_id]["future"] = future
        return jsonify(services.bracket_merge_tasks[task_id]["status"]), 202

    @app.get("/api/bracket-merge/download/<output_id>/<filename>")
    def bracket_merge_download(output_id: str, filename: str):
        try:
            output_path = resolve_merge_output(output_id, filename)
        except FileNotFoundError:
            abort(404)
        return send_cached_file(output_path, mimetype="image/jpeg", as_attachment=True, download_name=filename)


def initial_task_status(task_id: str, root_id: str, folder: str) -> dict:
    return {
        "taskId": task_id,
        "root": root_id,
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


def run_bracket_merge_task(
    services: AppServices,
    task_id: str,
    root_id: str,
    cached: dict,
    group_ids: list[int],
    params: dict,
) -> None:
    root_services = _root_services(services, root_id)

    def progress(stage: str, processed: int, total: int) -> None:
        with BRACKET_TASK_LOCK:
            task = services.bracket_merge_tasks.get(task_id)
            if task:
                task["status"].update({
                    "state": "running",
                    "stage": stage,
                    "processed": processed,
                    "total": total,
                    "progress": 1.0 if total <= 0 else round(processed / total, 6),
                })

    try:
        progress("正在准备合成", 0, len(group_ids))
        result = merge_bracket_groups(
            root_services.root,
            unroot_bracket_result(cached, root_id).get("groups", []),
            group_ids,
            params,
            progress_callback=progress,
        )
        with BRACKET_TASK_LOCK:
            task = services.bracket_merge_tasks.get(task_id)
            if task:
                task["status"].update({
                    "state": "done",
                    "stage": "合成完成",
                    "progress": 1.0,
                    "processed": len(group_ids),
                    "total": len(group_ids),
                    "result": result,
                })
    except Exception as error:
        with BRACKET_TASK_LOCK:
            task = services.bracket_merge_tasks.get(task_id)
            if task:
                task["status"].update({
                    "state": "error",
                    "stage": "合成失败",
                    "message": str(error),
                })


def run_bracket_detection_task(services: AppServices, root_id: str, folder: str, folder_path, thumbnails, task_id: str) -> None:
    started_at = perf_counter()
    with BRACKET_TASK_LOCK:
        task = services.bracket_tasks.get(task_id)
        if task:
            task["status"].update(initial_task_status(task_id, root_id, folder) | {"state": "running", "elapsedSeconds": 0.0})

    def progress_callback(stage: str, processed: int, total: int, groups_count: int) -> None:
        elapsed = perf_counter() - started_at
        progress = 1.0 if total <= 0 else processed / total
        eta = None
        if processed > 0 and total > processed:
            eta = (elapsed / processed) * (total - processed)
        with BRACKET_TASK_LOCK:
            task = services.bracket_tasks.get(task_id)
            if task:
                task["status"].update(
                    {
                        "taskId": task_id,
                        "root": root_id,
                        "folder": folder,
                        "state": "running",
                        "stage": stage,
                        "progress": round(progress, 6),
                        "processed": processed,
                        "total": total,
                        "count": groups_count,
                        "elapsedSeconds": round(elapsed, 3),
                        "etaSeconds": round(eta, 3) if eta is not None else None,
                    }
                )

    try:
        raw_result = detect_exposure_brackets(
            _root_services(services, root_id).root,
            folder_path,
            thumbnails,
            scan_limit=None,
            progress_callback=progress_callback,
        )
        result = root_bracket_result(raw_result, root_id)
        elapsed = perf_counter() - started_at
        status = {
            "taskId": task_id,
            "root": root_id,
            "folder": folder,
            "state": "done",
            "progress": 1.0,
            "processed": result["processed"],
            "total": result["total"],
            "elapsedSeconds": round(elapsed, 3),
            "etaSeconds": 0.0,
            **result,
        }
        with BRACKET_TASK_LOCK:
            services.bracket_cache[bracket_cache_key(root_id, folder)] = result
            save_bracket_cache(services)
            task = services.bracket_tasks.get(task_id)
            if task:
                task["status"] = status
    except Exception as error:
        with BRACKET_TASK_LOCK:
            task = services.bracket_tasks.get(task_id)
            if task:
                task["status"] = {
                    "taskId": task_id,
                    "root": root_id,
                    "folder": folder,
                    "state": "error",
                    "message": str(error),
                }


def bracket_cache_key(root_id: str, folder: str) -> str:
    normalized = normalize_bracket_folder(root_id, folder)
    return f"{root_id}/{normalized}".rstrip("/")


def ensure_bracket_cache_loaded(services: AppServices) -> None:
    if services.bracket_cache_loaded:
        return
    with BRACKET_TASK_LOCK:
        if services.bracket_cache_loaded:
            return
        services.bracket_cache.update(load_bracket_cache_file())
        services.bracket_cache_loaded = True


def load_bracket_cache_file() -> dict[str, dict]:
    if not BRACKET_CACHE_FILE.exists():
        return {}
    try:
        data = json.loads(BRACKET_CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): value for key, value in data.items() if isinstance(value, dict)}


def save_bracket_cache(services: AppServices) -> None:
    try:
        BRACKET_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        BRACKET_CACHE_FILE.write_text(
            json.dumps(services.bracket_cache, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
    except OSError:
        return


def normalize_bracket_folder(root_id: str, folder: str) -> str:
    value = (folder or "").replace("\\", "/").strip("/")
    prefix = f"{root_id}/"
    if value == root_id:
        return ""
    if value.startswith(prefix):
        return value[len(prefix):]
    return value


def root_bracket_result(result: dict, root_id: str) -> dict:
    rooted = {**result, "groups": []}
    for group in result.get("groups", []):
        rooted_group = {**group, "photos": []}
        for photo in group.get("photos", []):
            path = photo["path"]
            rooted_path = path if path == root_id or path.startswith(f"{root_id}/") else join_rooted_path(root_id, path)
            rooted_group["photos"].append({
                **photo,
                "path": rooted_path,
                "thumbUrl": f"/api/thumb/{quote_path(rooted_path)}",
            })
        rooted["groups"].append(rooted_group)
    return rooted


def unroot_bracket_result(result: dict, root_id: str) -> dict:
    prefix = f"{root_id}/"
    unrooted = {**result, "groups": []}
    for group in result.get("groups", []):
        unrooted_group = {**group, "photos": []}
        for photo in group.get("photos", []):
            path = photo.get("path", "")
            rel_path = path[len(prefix):] if path.startswith(prefix) else path
            unrooted_group["photos"].append({**photo, "path": rel_path})
        unrooted["groups"].append(unrooted_group)
    return unrooted


def find_active_task_for_folder(services: AppServices, root_id: str, folder: str) -> dict | None:
    for task in services.bracket_tasks.values():
        status = task.get("status", {})
        if status.get("root") == root_id and status.get("folder") == folder and status.get("state") in {"queued", "running"}:
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
