from __future__ import annotations

import json
import mimetypes
import uuid
from pathlib import Path
from typing import Any
from urllib import parse, request
from urllib.error import HTTPError, URLError

from .base import ProviderError


DEFAULT_TIMEOUT = 60
MAX_ERROR_BODY = 500


def json_request(
    url: str,
    *,
    method: str = "POST",
    payload: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    body = None
    request_headers = dict(headers or {})
    if params:
        query = parse.urlencode({key: value for key, value in params.items() if value is not None})
        separator = "&" if parse.urlparse(url).query else "?"
        url = f"{url}{separator}{query}"
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    request_headers.setdefault("Accept", "application/json")
    raw = raw_request(url, method=method, data=body, headers=request_headers, timeout=timeout)
    if not raw:
        return {}
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderError("云盘接口返回了无法解析的数据。") from exc
    if not isinstance(decoded, dict):
        raise ProviderError("云盘接口返回格式异常。")
    return decoded


def put_bytes(url: str, data: bytes, *, headers: dict[str, str] | None = None, timeout: int = DEFAULT_TIMEOUT) -> bytes:
    return raw_request(url, method="PUT", data=data, headers=headers or {}, timeout=timeout)


def multipart_request(
    url: str,
    *,
    fields: dict[str, str],
    file_field: str,
    filename: str,
    data: bytes,
    headers: dict[str, str] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    boundary = f"----photo-share-{uuid.uuid4().hex}"
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode("ascii"))
        chunks.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
        chunks.append(str(value).encode("utf-8"))
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}\r\n".encode("ascii"))
    chunks.append(
        (
            f'Content-Disposition: form-data; name="{file_field}"; filename="{Path(filename).name}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
    )
    chunks.append(data)
    chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    request_headers = dict(headers or {})
    request_headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    raw = raw_request(
        url,
        method="POST",
        data=b"".join(chunks),
        headers=request_headers,
        timeout=timeout,
    )
    if not raw:
        return {}
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderError("云盘接口返回了无法解析的数据。") from exc
    if not isinstance(decoded, dict):
        raise ProviderError("云盘接口返回格式异常。")
    return decoded


def raw_request(
    url: str,
    *,
    method: str,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> bytes:
    req = request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return response.read()
    except HTTPError as exc:
        detail = _read_error_body(exc)
        raise ProviderError(f"云盘接口请求失败：HTTP {exc.code}{detail}") from exc
    except URLError as exc:
        raise ProviderError(f"无法连接云盘接口：{exc.reason}") from exc


def unwrap_code_response(payload: dict[str, Any], service_name: str) -> Any:
    code = payload.get("code", 0)
    if code not in (0, "0", None):
        message = payload.get("message") or payload.get("msg") or f"code={code}"
        raise ProviderError(f"{service_name} 接口返回错误：{message}")
    return payload.get("data")


def _read_error_body(error: HTTPError) -> str:
    try:
        body = error.read(MAX_ERROR_BODY)
    except OSError:
        return ""
    if not body:
        return ""
    try:
        text = body.decode("utf-8", errors="replace").strip()
    except OSError:
        return ""
    return f"：{text[:MAX_ERROR_BODY]}" if text else ""
