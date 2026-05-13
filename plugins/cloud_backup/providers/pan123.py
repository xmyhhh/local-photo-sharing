from __future__ import annotations

import hashlib
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .base import BackupProvider, ProviderError
from .http import json_request, multipart_request, unwrap_code_response


API_BASE = "https://open-api.123pan.com"
SINGLE_UPLOAD_LIMIT = 64 * 1024 * 1024
DEFAULT_SLICE_SIZE = 64 * 1024 * 1024


class Pan123Provider(BackupProvider):
    key = "pan123"
    title = "123 云盘"
    available = True

    def __init__(self, settings: dict[str, Any]) -> None:
        super().__init__(settings)
        self._access_token = str(settings.get("pan123AccessToken") or "").strip()
        self._changed: dict[str, Any] = {}

    def validate(self) -> None:
        self._ensure_access_token()

    def upload_file(self, source: Path, remote_path: str) -> dict[str, Any]:
        self.validate()
        parent_id, filename = self._resolve_parent(remote_path, create=True)
        size = source.stat().st_size
        etag = md5_file(source)
        created = self._request(
            "/upload/v2/file/create",
            payload={
                "parentFileID": parent_id,
                "filename": filename,
                "etag": etag,
                "size": size,
                "duplicate": 2,
            },
        )
        file_id = parse_int(created.get("fileID") or created.get("fileId"), 0)
        if bool(created.get("reuse")) and file_id:
            return {"remotePath": normalize_remote_path(remote_path), "fileId": str(file_id), "size": size}
        if bool(created.get("reuse")):
            return {"remotePath": normalize_remote_path(remote_path), "size": size}
        upload_base = self._upload_base(created)
        if size <= SINGLE_UPLOAD_LIMIT:
            file_id = self._upload_single(source, upload_base, parent_id, filename, etag, size)
        else:
            file_id = self._upload_slices(source, upload_base, created, size)
        result = {"remotePath": normalize_remote_path(remote_path), "size": size}
        if file_id:
            result["fileId"] = str(file_id)
        return result

    def remote_file_matches(self, remote_path: str, size: int) -> bool:
        try:
            parent_id, filename = self._resolve_parent(remote_path, create=False)
            if parent_id < 0:
                return False
            item = self._find_child(parent_id, filename, expected_type=0)
            return bool(item and int(item.get("size") or -1) == size)
        except Exception:
            return False

    def updated_settings(self) -> dict[str, Any]:
        return dict(self._changed)

    def _ensure_access_token(self) -> None:
        expires_at = parse_int(self.settings.get("pan123TokenExpiresAt"), 0)
        if self._access_token and expires_at > int(time.time()) + 60:
            return
        client_id = str(self.settings.get("pan123ClientId") or "").strip()
        client_secret = str(self.settings.get("pan123ClientSecret") or "").strip()
        if not client_id or not client_secret:
            raise ProviderError("请先填写 123 云盘 Client ID 和 Client Secret。")
        payload = {"clientID": client_id, "clientSecret": client_secret}
        data = json_request(
            f"{API_BASE}/api/v1/access_token",
            payload=payload,
            headers={"Platform": "open_platform"},
        )
        if data.get("code") not in (0, "0", None) and "client" in str(data.get("message") or data.get("msg") or "").lower():
            data = json_request(
                f"{API_BASE}/api/v1/access_token",
                payload={"clientId": client_id, "clientSecret": client_secret},
                headers={"Platform": "open_platform"},
            )
        token_data = unwrap_code_response(data, "123 云盘")
        if not isinstance(token_data, dict):
            raise ProviderError("123 云盘 token 返回格式异常。")
        access_token = str(token_data.get("accessToken") or "").strip()
        if not access_token:
            raise ProviderError("123 云盘 token 返回为空。")
        expires_at = parse_expired_at(str(token_data.get("expiredAt") or ""))
        self._access_token = access_token
        self._changed.update({"pan123AccessToken": access_token, "pan123TokenExpiresAt": expires_at})

    def _resolve_parent(self, remote_path: str, *, create: bool) -> tuple[int, str]:
        parts = split_remote_path(remote_path)
        if not parts:
            raise ProviderError("远端备份路径为空。")
        parent_id = parse_int(self.settings.get("pan123RootFileId"), 0)
        for name in parts[:-1]:
            item = self._find_child(parent_id, name, expected_type=1)
            if item:
                parent_id = parse_int(item.get("fileId") or item.get("fileID"), parent_id)
                continue
            if not create:
                return -1, parts[-1]
            parent_id = self._create_folder(parent_id, name)
        return parent_id, parts[-1]

    def _find_child(self, parent_id: int, name: str, *, expected_type: int | None = None) -> dict[str, Any] | None:
        last_file_id = 0
        while True:
            data = self._request(
                "/api/v2/file/list",
                method="GET",
                params={"parentFileId": parent_id, "limit": 100, "lastFileId": last_file_id},
            )
            files = data.get("fileList") if isinstance(data.get("fileList"), list) else []
            for item in files:
                if item.get("filename") != name:
                    continue
                if int(item.get("trashed") or 0):
                    continue
                item_type = parse_int(item.get("type"), -1)
                if expected_type is None or item_type == expected_type:
                    return item
            next_file_id = parse_int(data.get("lastFileId") or data.get("lastFileID"), 0)
            if not next_file_id or next_file_id == last_file_id:
                return None
            last_file_id = next_file_id

    def _create_folder(self, parent_id: int, name: str) -> int:
        data = self._request("/upload/v1/file/mkdir", payload={"name": name, "parentID": parent_id})
        folder_id = parse_int(data.get("dirID") or data.get("fileID") or data.get("fileId"), 0)
        if not folder_id:
            existing = self._find_child(parent_id, name, expected_type=1)
            folder_id = parse_int(existing.get("fileId") or existing.get("fileID"), 0) if existing else 0
        if not folder_id:
            raise ProviderError(f"123 云盘创建目录失败：{name}")
        return folder_id

    def _upload_single(self, source: Path, upload_base: str, parent_id: int, filename: str, etag: str, size: int) -> int:
        data = multipart_request(
            f"{upload_base}/upload/v2/file/single/create",
            fields={
                "parentFileID": str(parent_id),
                "filename": filename,
                "etag": etag,
                "size": str(size),
                "duplicate": "2",
            },
            file_field="file",
            filename=filename,
            data=source.read_bytes(),
            headers=self._headers(),
            timeout=600,
        )
        result = unwrap_code_response(data, "123 云盘")
        if not isinstance(result, dict):
            raise ProviderError("123 云盘单文件上传返回格式异常。")
        if not result.get("completed"):
            raise ProviderError("123 云盘单文件上传未完成。")
        return parse_int(result.get("fileID") or result.get("fileId"), 0)

    def _upload_slices(self, source: Path, upload_base: str, created: dict[str, Any], size: int) -> int:
        preupload_id = str(created.get("preuploadID") or created.get("preuploadId") or "").strip()
        if not preupload_id:
            raise ProviderError("123 云盘没有返回 preuploadID。")
        slice_size = parse_int(created.get("sliceSize"), DEFAULT_SLICE_SIZE)
        slice_size = max(1024 * 1024, slice_size)
        total = max(1, math.ceil(size / slice_size))
        with source.open("rb") as handle:
            for number in range(1, total + 1):
                chunk = handle.read(slice_size)
                if not chunk and size > 0:
                    raise ProviderError("读取本地文件时提前结束。")
                chunk_md5 = hashlib.md5(chunk).hexdigest()
                data = multipart_request(
                    f"{upload_base}/upload/v2/file/slice",
                    fields={
                        "preuploadID": preupload_id,
                        "sliceNo": str(number),
                        "sliceMD5": chunk_md5,
                    },
                    file_field="slice",
                    filename=f"{source.name}.part{number}",
                    data=chunk,
                    headers=self._headers(),
                    timeout=600,
                )
                unwrap_code_response(data, "123 云盘")
        complete = self._request(f"{upload_base}/upload/v2/file/upload_complete", payload={"preuploadID": preupload_id}, full_url=True)
        if bool(complete.get("completed")):
            return parse_int(complete.get("fileID") or complete.get("fileId"), 0)
        for _ in range(40):
            time.sleep(1)
            complete = self._request(f"{upload_base}/upload/v2/file/upload_complete", payload={"preuploadID": preupload_id}, full_url=True)
            completed = bool(complete.get("completed"))
            file_id = parse_int(complete.get("fileID") or complete.get("fileId"), 0)
            if completed:
                return file_id
        raise ProviderError("123 云盘上传完成确认超时。")

    def _upload_base(self, created: dict[str, Any]) -> str:
        servers = created.get("servers") if isinstance(created.get("servers"), list) else []
        if not servers:
            raise ProviderError("123 云盘没有返回上传域名。")
        return str(servers[0]).rstrip("/")

    def _request(
        self,
        endpoint: str,
        *,
        method: str = "POST",
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        full_url: bool = False,
        retry: bool = True,
    ) -> Any:
        self._ensure_access_token()
        url = endpoint if full_url else f"{API_BASE}{endpoint}"
        try:
            data = json_request(url, method=method, payload=payload, params=params, headers=self._headers())
        except ProviderError as exc:
            if retry and "401" in str(exc):
                self._access_token = ""
                self._changed["pan123AccessToken"] = ""
                self._changed["pan123TokenExpiresAt"] = 0
                self._ensure_access_token()
                return self._request(
                    endpoint,
                    method=method,
                    payload=payload,
                    params=params,
                    full_url=full_url,
                    retry=False,
                )
            raise
        try:
            return unwrap_code_response(data, "123 云盘")
        except ProviderError as exc:
            if "401" in str(exc):
                self._access_token = ""
                self._changed["pan123AccessToken"] = ""
                self._changed["pan123TokenExpiresAt"] = 0
                if retry:
                    self._ensure_access_token()
                    return self._request(
                        endpoint,
                        method=method,
                        payload=payload,
                        params=params,
                        full_url=full_url,
                        retry=False,
                    )
            raise

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._access_token}", "Platform": "open_platform"}


def md5_file(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_remote_path(value: str) -> str:
    return "/".join(split_remote_path(value))


def split_remote_path(value: str) -> list[str]:
    return [
        part.strip()
        for part in str(value).replace("\\", "/").split("/")
        if part.strip() and part.strip() not in {".", ".."}
    ]


def parse_expired_at(value: str) -> int:
    text = value.strip()
    if not text:
        return int(time.time()) + 7200
    formats = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"]
    normalized = text.replace("Z", "+00:00")
    for fmt in formats:
        try:
            parsed = datetime.strptime(normalized, fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return int(parsed.timestamp())
        except ValueError:
            continue
    try:
        return int(datetime.fromisoformat(normalized).timestamp())
    except ValueError:
        return int(time.time()) + 7200


def parse_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback
