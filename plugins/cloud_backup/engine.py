from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.photo_share.constants import APP_DIR, MEDIA_EXTENSIONS, RATINGS_FILE, THUMBNAIL_DIR
from core.photo_share.context import AppServices
from core.photo_share.paths import to_relative

from cloud_backup.providers import BackupProvider, LocalFolderProvider, ProviderError

PLUGIN_NAME = "cloud_backup"
BACKUP_STATE_DIR = APP_DIR / ".photo_share_backup"
SETTINGS_FILE = BACKUP_STATE_DIR / "settings.json"
MANIFEST_FILE = BACKUP_STATE_DIR / "manifest.json"
RUN_HISTORY_LIMIT = 20
DEFAULT_SETTINGS = {
    "enabled": False,
    "provider": "local_folder",
    "targetDir": "",
    "remotePrefix": "photo-share-backup",
    "intervalHours": 24,
    "maxFilesPerRun": 0,
    "checksum": "size_mtime",
}
IGNORED_DIR_NAMES = {
    ".git",
    ".idea",
    ".photo_share_backup",
    ".photo_share_cache",
    ".photo_share_thumbs",
    ".photo_share_trash",
    ".photo_share_bracket_results",
    "__pycache__",
}
IGNORED_FILE_NAMES = {
    RATINGS_FILE,
    "bracket_project.prj",
}
PROVIDERS: dict[str, type[BackupProvider]] = {
    "local_folder": LocalFolderProvider,
}
PLANNED_PROVIDERS = [
    {"key": "aliyundrive", "title": "阿里云盘", "available": False, "planned": True},
    {"key": "pan123", "title": "123 云盘", "available": False, "planned": True},
]


@dataclass(frozen=True, slots=True)
class BackupCandidate:
    root_id: str
    root: Path
    path: Path
    rel: str
    keyed_path: str
    remote_path: str
    size: int
    mtime: int


class CloudBackupEngine:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._services: AppServices | None = None
        self._settings = normalize_settings({})
        self._manifest: dict[str, Any] = {"version": 1, "files": {}, "runs": []}
        self._run: dict[str, Any] | None = None
        self._last_run_at = 0.0
        self._next_run_at = 0.0

    def start(self, services: AppServices) -> None:
        with self._lock:
            self._services = services
            self._settings = load_settings()
            self._manifest = load_manifest()
            self._stop.clear()
            self._schedule_next_locked()
            if self._thread and self._thread.is_alive():
                self._wake.set()
                return
            self._thread = threading.Thread(target=self._run_loop, name="cloud-backup", daemon=True)
            self._thread.start()
            self._wake.set()

    def stop(self) -> None:
        with self._lock:
            self._stop.set()
            self._wake.set()
            thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2)
        with self._lock:
            self._thread = None
            self._services = None
            self._run = None
            self._next_run_at = 0.0

    def settings_payload(self) -> dict[str, Any]:
        with self._lock:
            settings = dict(self._settings)
            status = self._status_locked()
        return {
            "settings": public_settings(settings),
            "status": status,
            "providers": provider_summaries(),
        }

    def update_settings(self, data: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            current = dict(self._settings)
            current.update(data)
            settings = normalize_settings(current)
            self._settings = settings
            save_settings(settings)
            self._schedule_next_locked()
            self._wake.set()
        return self.settings_payload()

    def run_now(self) -> dict[str, Any]:
        with self._lock:
            if self._run and self._run.get("state") in {"queued", "running", "scanning"}:
                return self._status_locked()
            self._run = self._new_run_locked(manual=True)
            self._wake.set()
            return self._status_locked()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return self._status_locked()

    def get_backend_tasks(self) -> list[dict[str, Any]]:
        with self._lock:
            run = dict(self._run or {})
        if run.get("state") not in {"queued", "running", "scanning", "error"}:
            return []
        total = int(run.get("total") or 0)
        completed = int(run.get("completed") or 0)
        progress = completed / total if total else None
        return [{
            "id": "cloud_backup.current",
            "source": PLUGIN_NAME,
            "title": "冷备份",
            "detail": str(run.get("detail") or run.get("providerTitle") or ""),
            "state": run.get("state") or "running",
            "progress": progress,
            "completed": completed if total else run.get("uploaded", 0),
            "total": total or None,
            "error": run.get("error", ""),
            "meta": {
                "uploaded": run.get("uploaded", 0),
                "skipped": run.get("skipped", 0),
                "failed": run.get("failed", 0),
                "bytesUploaded": run.get("bytesUploaded", 0),
            },
        }]

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            wait_seconds = self._seconds_until_next_run()
            self._wake.wait(wait_seconds)
            self._wake.clear()
            if self._stop.is_set():
                break
            services = self._services
            if services is None:
                continue
            if not self._should_run_now():
                continue
            self._execute_run(services)

    def _seconds_until_next_run(self) -> float:
        with self._lock:
            if self._run and self._run.get("state") == "queued":
                return 0
            if not self._settings.get("enabled"):
                return 3600
            if not self._next_run_at:
                return 10
            return max(1.0, self._next_run_at - time.time())

    def _should_run_now(self) -> bool:
        with self._lock:
            if self._run and self._run.get("state") == "queued":
                return True
            return bool(self._settings.get("enabled") and self._next_run_at and time.time() >= self._next_run_at)

    def _execute_run(self, services: AppServices) -> None:
        with self._lock:
            settings = dict(self._settings)
            if not self._run or self._run.get("state") not in {"queued", "running", "scanning"}:
                self._run = self._new_run_locked(manual=False)
            run_id = self._run["id"]
        try:
            provider = create_provider(settings)
            provider.validate()
            validate_provider_target(services, provider)
            candidates = list(iter_backup_candidates(services, settings))
            max_files = int(settings.get("maxFilesPerRun") or 0)
            if max_files > 0:
                candidates = candidates[:max_files]
            with self._lock:
                if not self._is_run_current_locked(run_id):
                    return
                self._run.update({
                    "state": "running",
                    "total": len(candidates),
                    "detail": "正在备份媒体文件",
                    "providerTitle": provider.title,
                })
            self._backup_candidates(run_id, provider, candidates)
            with self._lock:
                if not self._is_run_current_locked(run_id):
                    return
                failed = int(self._run.get("failed") or 0)
                self._run["state"] = "error" if failed else "ready"
                self._run["finishedAt"] = int(time.time())
                self._run["detail"] = "部分文件备份失败" if failed else "备份完成"
                self._last_run_at = float(self._run["finishedAt"])
                self._add_run_history_locked(dict(self._run))
                save_manifest(self._manifest)
                self._schedule_next_locked()
        except Exception as exc:  # noqa: BLE001 - background backup must keep the app alive.
            with self._lock:
                if self._run and self._run.get("id") == run_id:
                    self._run["state"] = "error"
                    self._run["error"] = str(exc)
                    self._run["finishedAt"] = int(time.time())
                    self._add_run_history_locked(dict(self._run))
                    save_manifest(self._manifest)
                    self._schedule_next_locked()

    def _backup_candidates(self, run_id: str, provider: BackupProvider, candidates: list[BackupCandidate]) -> None:
        for index, candidate in enumerate(candidates, 1):
            if self._stop.is_set():
                break
            with self._lock:
                if not self._is_run_current_locked(run_id):
                    return
                self._run["completed"] = index - 1
                self._run["detail"] = candidate.keyed_path
            if self._is_file_current(candidate, provider):
                self._mark_skipped(run_id, candidate)
                continue
            try:
                digest = sha256_file(candidate.path)
                if self._is_file_current(candidate, provider, digest=digest):
                    self._mark_skipped(run_id, candidate, digest=digest)
                    continue
                result = provider.upload_file(candidate.path, candidate.remote_path)
            except Exception as exc:  # noqa: BLE001 - one bad file should not stop the whole backup.
                self._record_failed(run_id, candidate, exc)
                continue
            self._record_uploaded(run_id, candidate, digest, result)

    def _is_file_current(self, candidate: BackupCandidate, provider: BackupProvider, digest: str = "") -> bool:
        with self._lock:
            record = dict(self._manifest.get("files", {}).get(candidate.keyed_path) or {})
        if not record:
            return False
        if record.get("provider") != self._settings.get("provider"):
            return False
        if record.get("remotePath") != candidate.remote_path:
            return False
        if int(record.get("size") or -1) != candidate.size or int(record.get("mtime") or -1) != candidate.mtime:
            return False
        if digest and record.get("sha256") and record.get("sha256") != digest:
            return False
        return provider.remote_file_matches(str(record.get("remotePath") or candidate.remote_path), candidate.size)

    def _mark_skipped(self, run_id: str, candidate: BackupCandidate, digest: str = "") -> None:
        with self._lock:
            if not self._is_run_current_locked(run_id):
                return
            self._run["completed"] = int(self._run.get("completed") or 0) + 1
            self._run["skipped"] = int(self._run.get("skipped") or 0) + 1
            if digest:
                record = self._manifest.setdefault("files", {}).setdefault(candidate.keyed_path, {})
                record["sha256"] = digest

    def _record_uploaded(self, run_id: str, candidate: BackupCandidate, digest: str, result: dict[str, Any]) -> None:
        now = int(time.time())
        with self._lock:
            if not self._is_run_current_locked(run_id):
                return
            self._manifest.setdefault("files", {})[candidate.keyed_path] = {
                "rootId": candidate.root_id,
                "rel": candidate.rel,
                "size": candidate.size,
                "mtime": candidate.mtime,
                "sha256": digest,
                "remotePath": result.get("remotePath") or candidate.remote_path,
                "provider": self._settings.get("provider"),
                "backedUpAt": now,
            }
            self._run["completed"] = int(self._run.get("completed") or 0) + 1
            self._run["uploaded"] = int(self._run.get("uploaded") or 0) + 1
            self._run["bytesUploaded"] = int(self._run.get("bytesUploaded") or 0) + candidate.size

    def _record_failed(self, run_id: str, candidate: BackupCandidate, error: Exception) -> None:
        with self._lock:
            if not self._is_run_current_locked(run_id):
                return
            self._run["completed"] = int(self._run.get("completed") or 0) + 1
            self._run["failed"] = int(self._run.get("failed") or 0) + 1
            self._run["error"] = f"{candidate.keyed_path}: {error}"

    def _status_locked(self) -> dict[str, Any]:
        files = self._manifest.get("files") if isinstance(self._manifest.get("files"), dict) else {}
        runs = self._manifest.get("runs") if isinstance(self._manifest.get("runs"), list) else []
        return {
            "enabled": bool(self._settings.get("enabled")),
            "provider": self._settings.get("provider"),
            "running": bool(self._run and self._run.get("state") in {"queued", "running", "scanning"}),
            "currentRun": dict(self._run) if self._run else None,
            "lastRun": runs[0] if runs else None,
            "history": runs[:RUN_HISTORY_LIMIT],
            "fileCount": len(files),
            "nextRunAt": int(self._next_run_at or 0),
        }

    def _new_run_locked(self, manual: bool) -> dict[str, Any]:
        return {
            "id": f"{int(time.time())}-{os.getpid()}",
            "state": "queued",
            "manual": manual,
            "startedAt": int(time.time()),
            "finishedAt": 0,
            "total": 0,
            "completed": 0,
            "uploaded": 0,
            "skipped": 0,
            "failed": 0,
            "bytesUploaded": 0,
            "detail": "等待开始",
            "error": "",
        }

    def _is_run_current_locked(self, run_id: str) -> bool:
        return bool(self._run and self._run.get("id") == run_id)

    def _add_run_history_locked(self, run: dict[str, Any]) -> None:
        runs = self._manifest.setdefault("runs", [])
        if isinstance(runs, list):
            runs.insert(0, public_run(run))
            del runs[RUN_HISTORY_LIMIT:]
        self._run = run

    def _schedule_next_locked(self) -> None:
        if not self._settings.get("enabled"):
            self._next_run_at = 0.0
            return
        interval = int(self._settings.get("intervalHours") or DEFAULT_SETTINGS["intervalHours"])
        base = self._last_run_at or latest_run_time(self._manifest) or time.time()
        self._next_run_at = base + max(1, interval) * 3600
        if latest_run_time(self._manifest) == 0:
            self._next_run_at = time.time() + 5


def iter_backup_candidates(services: AppServices, settings: dict[str, Any]):
    prefix = normalize_remote_prefix(str(settings.get("remotePrefix") or ""))
    for root_id, root in services.roots.items():
        root = root.resolve()
        for path in iter_media_files(root):
            try:
                stat = path.stat()
                rel = to_relative(root, path)
            except OSError:
                continue
            keyed_path = f"{root_id}/{rel}"
            remote_path = "/".join(part for part in [prefix, root_id, rel] if part)
            yield BackupCandidate(
                root_id=root_id,
                root=root,
                path=path,
                rel=rel,
                keyed_path=keyed_path,
                remote_path=remote_path,
                size=stat.st_size,
                mtime=int(stat.st_mtime),
            )


def iter_media_files(root: Path):
    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        dirs[:] = [
            name
            for name in dirs
            if name not in IGNORED_DIR_NAMES and not name.startswith(".photo_share_")
        ]
        for name in files:
            if name in IGNORED_FILE_NAMES or name.endswith(".prj"):
                continue
            path = current_path / name
            try:
                if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS:
                    yield path
            except OSError:
                continue


def create_provider(settings: dict[str, Any]) -> BackupProvider:
    provider_key = str(settings.get("provider") or "local_folder")
    provider_type = PROVIDERS.get(provider_key)
    if provider_type is None:
        raise ProviderError(f"暂不支持这个备份目标：{provider_key}")
    return provider_type(settings)


def validate_provider_target(services: AppServices, provider: BackupProvider) -> None:
    if isinstance(provider, LocalFolderProvider):
        target = provider.target_dir().resolve()
        prefix = normalize_remote_prefix(str(provider.settings.get("remotePrefix") or ""))
        upload_base = (target / prefix).resolve() if prefix else target
        for root in services.roots.values():
            root = root.resolve()
            try:
                upload_base.relative_to(root)
            except ValueError:
                continue
            raise ProviderError("本地备份目录不能放在图库目录里面，否则会循环备份。")


def provider_summaries() -> list[dict[str, Any]]:
    summaries = [
        {"key": provider.key, "title": provider.title, "available": provider.available, "planned": False}
        for provider in PROVIDERS.values()
    ]
    summaries.extend(PLANNED_PROVIDERS)
    return summaries


def normalize_settings(value: dict[str, Any]) -> dict[str, Any]:
    settings = dict(DEFAULT_SETTINGS)
    if isinstance(value, dict):
        settings.update(value)
    provider = str(settings.get("provider") or DEFAULT_SETTINGS["provider"])
    if provider not in PROVIDERS:
        provider = DEFAULT_SETTINGS["provider"]
    settings["provider"] = provider
    settings["enabled"] = bool(settings.get("enabled", False))
    settings["targetDir"] = str(settings.get("targetDir") or "").strip()
    settings["remotePrefix"] = normalize_remote_prefix(str(settings.get("remotePrefix") or DEFAULT_SETTINGS["remotePrefix"]))
    settings["intervalHours"] = parse_int(settings.get("intervalHours"), 1, 24 * 30, DEFAULT_SETTINGS["intervalHours"])
    settings["maxFilesPerRun"] = parse_int(settings.get("maxFilesPerRun"), 0, 1_000_000, DEFAULT_SETTINGS["maxFilesPerRun"])
    settings["checksum"] = "size_mtime"
    return settings


def public_settings(settings: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": bool(settings.get("enabled")),
        "provider": settings.get("provider"),
        "targetDir": settings.get("targetDir", ""),
        "remotePrefix": settings.get("remotePrefix", ""),
        "intervalHours": settings.get("intervalHours"),
        "maxFilesPerRun": settings.get("maxFilesPerRun"),
        "checksum": settings.get("checksum", "sha256"),
    }


def public_run(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": run.get("id"),
        "state": run.get("state"),
        "manual": bool(run.get("manual")),
        "startedAt": run.get("startedAt", 0),
        "finishedAt": run.get("finishedAt", 0),
        "total": run.get("total", 0),
        "completed": run.get("completed", 0),
        "uploaded": run.get("uploaded", 0),
        "skipped": run.get("skipped", 0),
        "failed": run.get("failed", 0),
        "bytesUploaded": run.get("bytesUploaded", 0),
        "detail": run.get("detail", ""),
        "error": run.get("error", ""),
    }


def normalize_remote_prefix(value: str) -> str:
    return "/".join(
        part.strip()
        for part in value.replace("\\", "/").split("/")
        if part.strip() and part.strip() not in {".", ".."}
    )


def parse_int(value: Any, minimum: int, maximum: int, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, parsed))


def load_settings() -> dict[str, Any]:
    try:
        raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {}
    return normalize_settings(raw if isinstance(raw, dict) else {})


def save_settings(settings: dict[str, Any]) -> None:
    BACKUP_STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(public_settings(settings), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, SETTINGS_FILE)


def load_manifest() -> dict[str, Any]:
    try:
        raw = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    files = raw.get("files") if isinstance(raw.get("files"), dict) else {}
    runs = raw.get("runs") if isinstance(raw.get("runs"), list) else []
    return {"version": 1, "files": files, "runs": runs[:RUN_HISTORY_LIMIT]}


def save_manifest(manifest: dict[str, Any]) -> None:
    BACKUP_STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = MANIFEST_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, MANIFEST_FILE)


def latest_run_time(manifest: dict[str, Any]) -> float:
    runs = manifest.get("runs") if isinstance(manifest.get("runs"), list) else []
    for run in runs:
        if isinstance(run, dict):
            value = run.get("finishedAt") or run.get("startedAt") or 0
            try:
                return float(value)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
