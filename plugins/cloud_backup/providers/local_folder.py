from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from .base import BackupProvider, ProviderError


class LocalFolderProvider(BackupProvider):
    key = "local_folder"
    title = "本地目录"
    available = True

    def validate(self) -> None:
        target = self.target_dir()
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ProviderError(f"无法创建备份目录：{target}") from exc
        if not target.is_dir():
            raise ProviderError(f"备份目录不可用：{target}")

    def upload_file(self, source: Path, remote_path: str) -> dict[str, Any]:
        target = self.target_dir() / normalize_remote_path(remote_path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(f".{target.name}.photo-share-uploading")
            shutil.copy2(source, tmp)
            os.replace(tmp, target)
            stat = target.stat()
        except OSError as exc:
            raise ProviderError(f"复制失败：{source.name}") from exc
        return {
            "remotePath": target.relative_to(self.target_dir()).as_posix(),
            "absolutePath": str(target),
            "size": stat.st_size,
            "mtime": int(stat.st_mtime),
        }

    def remote_file_matches(self, remote_path: str, size: int) -> bool:
        target = self.target_dir() / normalize_remote_path(remote_path)
        try:
            return target.is_file() and target.stat().st_size == size
        except OSError:
            return False

    def target_dir(self) -> Path:
        value = str(self.settings.get("targetDir") or "").strip()
        if not value:
            raise ProviderError("请先设置本地备份目录。")
        return Path(value).expanduser().resolve()


def normalize_remote_path(value: str) -> Path:
    normalized = Path(str(value).replace("\\", "/"))
    if normalized.is_absolute() or ".." in normalized.parts:
        raise ProviderError("备份路径不安全。")
    return normalized
