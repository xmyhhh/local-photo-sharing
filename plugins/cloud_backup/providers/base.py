from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class ProviderError(RuntimeError):
    pass


class BackupProvider(ABC):
    key: str = ""
    title: str = ""
    available: bool = False

    def __init__(self, settings: dict[str, Any]) -> None:
        self.settings = settings

    @abstractmethod
    def validate(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def upload_file(self, source: Path, remote_path: str) -> dict[str, Any]:
        raise NotImplementedError

    def remote_file_matches(self, remote_path: str, size: int) -> bool:
        return True

    def updated_settings(self) -> dict[str, Any]:
        return {}
