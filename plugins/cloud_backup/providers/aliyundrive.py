from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Any

from .base import BackupProvider, ProviderError
from .http import json_request, put_bytes


API_BASE = "https://openapi.alipan.com"
LEGACY_API_BASE = "https://openapi.aliyundrive.com"
PART_SIZE = 8 * 1024 * 1024
MAX_PARTS = 10_000


class AliyunDriveProvider(BackupProvider):
    key = "aliyundrive"
    title = "阿里云盘"
    available = True

    def __init__(self, settings: dict[str, Any]) -> None:
        super().__init__(settings)
        self._access_token = str(settings.get("aliyunAccessToken") or "").strip()
        self._refresh_token = str(settings.get("aliyunRefreshToken") or "").strip()
        self._drive_id = str(settings.get("aliyunDriveId") or "").strip()
        self._api_base = str(settings.get("aliyunApiBase") or API_BASE).strip() or API_BASE
        self._changed: dict[str, Any] = {}

    def validate(self) -> None:
        self._ensure_access_token()
        self._ensure_drive_id()

    def upload_file(self, source: Path, remote_path: str) -> dict[str, Any]:
        self.validate()
        parent_id, filename = self._resolve_parent(remote_path, create=True)
        size = source.stat().st_size
        existing = self._find_child(parent_id, filename, expected_type="file")
        if existing and int(existing.get("size") or -1) == size:
            return {
                "remotePath": normalize_remote_path(remote_path),
                "fileId": existing.get("file_id"),
                "size": size,
            }
        if existing:
            self._trash_file(str(existing.get("file_id") or ""))
        part_count = max(1, math.ceil(size / PART_SIZE))
        if part_count > MAX_PARTS:
            raise ProviderError("阿里云盘上传分片数量过多，请调整分片大小。")
        create_payload = {
            "drive_id": self._drive_id,
            "parent_file_id": parent_id,
            "name": filename,
            "type": "file",
            "check_name_mode": "ignore",
            "size": size,
            "part_info_list": [{"part_number": number} for number in range(1, part_count + 1)],
        }
        created = self._api("/adrive/v1.0/openFile/create", create_payload)
        if created.get("rapid_upload"):
            return {"remotePath": normalize_remote_path(remote_path), "fileId": created.get("file_id"), "size": size}
        upload_id = str(created.get("upload_id") or "")
        file_id = str(created.get("file_id") or "")
        parts = created.get("part_info_list")
        if not upload_id or not file_id or not isinstance(parts, list):
            raise ProviderError("阿里云盘没有返回完整的上传地址。")
        with source.open("rb") as handle:
            for part in parts:
                upload_url = str(part.get("upload_url") or "")
                if not upload_url:
                    raise ProviderError("阿里云盘分片上传地址为空。")
                chunk = handle.read(PART_SIZE)
                headers = {"Content-Type": str(part.get("content_type") or "application/octet-stream")}
                put_bytes(upload_url, chunk, headers=headers)
                if not chunk and size > 0:
                    raise ProviderError("读取本地文件时提前结束。")
        completed = self._api(
            "/adrive/v1.0/openFile/complete",
            {"drive_id": self._drive_id, "file_id": file_id, "upload_id": upload_id},
        )
        return {
            "remotePath": normalize_remote_path(remote_path),
            "fileId": completed.get("file_id") or file_id,
            "size": size,
        }

    def remote_file_matches(self, remote_path: str, size: int) -> bool:
        try:
            parent_id, filename = self._resolve_parent(remote_path, create=False)
            if not parent_id:
                return False
            item = self._find_child(parent_id, filename, expected_type="file")
            return bool(item and int(item.get("size") or -1) == size)
        except Exception:
            return False

    def updated_settings(self) -> dict[str, Any]:
        return dict(self._changed)

    def _ensure_access_token(self) -> None:
        expires_at = parse_int(self.settings.get("aliyunTokenExpiresAt"), 0)
        if self._access_token and (not expires_at or expires_at > int(time.time()) + 60):
            return
        if not self._refresh_token:
            raise ProviderError("请先填写阿里云盘 refresh token。")
        client_id = str(self.settings.get("aliyunClientId") or "").strip()
        client_secret = str(self.settings.get("aliyunClientSecret") or "").strip()
        if not client_id or not client_secret:
            raise ProviderError("阿里云盘刷新 token 需要 Client ID 和 Client Secret。")
        payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
        }
        data = json_request(f"{API_BASE}/oauth/access_token", payload=payload)
        if data.get("code") not in (0, "0", None, ""):
            raise ProviderError(f"阿里云盘 token 刷新失败：{data.get('message') or data.get('code')}")
        access_token = str(data.get("access_token") or "").strip()
        refresh_token = str(data.get("refresh_token") or self._refresh_token).strip()
        if not access_token:
            raise ProviderError("阿里云盘 token 刷新失败：access_token 为空。")
        expires_in = parse_int(data.get("expires_in"), 7200)
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._changed.update({
            "aliyunAccessToken": access_token,
            "aliyunRefreshToken": refresh_token,
            "aliyunTokenExpiresAt": int(time.time()) + max(300, expires_in) - 60,
        })

    def _ensure_drive_id(self) -> None:
        if self._drive_id:
            return
        info = self._api("/adrive/v1.0/user/getDriveInfo", {})
        drive_type = str(self.settings.get("aliyunDriveType") or "default").strip() or "default"
        keys = [f"{drive_type}_drive_id", "default_drive_id", "resource_drive_id", "backup_drive_id"]
        for key in keys:
            value = str(info.get(key) or "").strip()
            if value:
                self._drive_id = value
                self._changed["aliyunDriveId"] = value
                return
        raise ProviderError("阿里云盘没有返回可用 drive_id。")

    def _resolve_parent(self, remote_path: str, *, create: bool) -> tuple[str, str]:
        parts = split_remote_path(remote_path)
        if not parts:
            raise ProviderError("远端备份路径为空。")
        parent_id = self._root_file_id()
        for name in parts[:-1]:
            item = self._find_child(parent_id, name, expected_type="folder")
            if item:
                parent_id = str(item.get("file_id") or "")
                continue
            if not create:
                return "", parts[-1]
            parent_id = self._create_folder(parent_id, name)
        return parent_id, parts[-1]

    def _root_file_id(self) -> str:
        return str(self.settings.get("aliyunRootFileId") or "root").strip() or "root"

    def _find_child(self, parent_id: str, name: str, *, expected_type: str | None = None) -> dict[str, Any] | None:
        marker = ""
        while True:
            data = self._api(
                "/adrive/v1.0/openFile/list",
                {
                    "drive_id": self._drive_id,
                    "parent_file_id": parent_id,
                    "limit": 200,
                    "marker": marker,
                },
            )
            items = data.get("items") if isinstance(data.get("items"), list) else []
            for item in items:
                if item.get("name") == name and (expected_type is None or item.get("type") == expected_type):
                    return item
            marker = str(data.get("next_marker") or "")
            if not marker:
                return None

    def _create_folder(self, parent_id: str, name: str) -> str:
        data = self._api(
            "/adrive/v1.0/openFile/create",
            {
                "drive_id": self._drive_id,
                "parent_file_id": parent_id,
                "name": name,
                "type": "folder",
                "check_name_mode": "ignore",
            },
        )
        file_id = str(data.get("file_id") or "")
        if not file_id:
            existing = self._find_child(parent_id, name, expected_type="folder")
            file_id = str(existing.get("file_id") or "") if existing else ""
        if not file_id:
            raise ProviderError(f"阿里云盘创建目录失败：{name}")
        return file_id

    def _trash_file(self, file_id: str) -> None:
        if not file_id:
            raise ProviderError("阿里云盘旧文件 file_id 为空，无法覆盖。")
        self._api("/adrive/v1.0/openFile/recyclebin/trash", {"drive_id": self._drive_id, "file_id": file_id})

    def _api(self, endpoint: str, payload: dict[str, Any], *, retry: bool = True) -> dict[str, Any]:
        self._ensure_access_token()
        try:
            data = json_request(
                f"{self._api_base}{endpoint}",
                payload=payload,
                headers={"Authorization": f"Bearer {self._access_token}"},
            )
        except ProviderError:
            if self._api_base == API_BASE:
                data = json_request(
                    f"{LEGACY_API_BASE}{endpoint}",
                    payload=payload,
                    headers={"Authorization": f"Bearer {self._access_token}"},
                )
                self._api_base = LEGACY_API_BASE
                self._changed["aliyunApiBase"] = LEGACY_API_BASE
            else:
                raise
        code = data.get("code")
        if code not in (0, "0", None, ""):
            if retry and str(code) in {"AccessTokenInvalid", "AccessTokenExpired", "I400JD"}:
                self._changed["aliyunAccessToken"] = ""
                self._access_token = ""
                self._ensure_access_token()
                return self._api(endpoint, payload, retry=False)
            raise ProviderError(f"阿里云盘接口错误：{data.get('message') or code}")
        return data


def normalize_remote_path(value: str) -> str:
    return "/".join(split_remote_path(value))


def split_remote_path(value: str) -> list[str]:
    return [
        part.strip()
        for part in str(value).replace("\\", "/").split("/")
        if part.strip() and part.strip() not in {".", ".."}
    ]


def parse_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback
