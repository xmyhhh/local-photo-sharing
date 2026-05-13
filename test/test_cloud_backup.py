from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

PLUGIN_PARENT = Path(__file__).resolve().parents[1] / "plugins"
if str(PLUGIN_PARENT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_PARENT))

from cloud_backup.engine import CloudBackupEngine, merge_settings_update, normalize_settings, provider_summaries, public_settings
from cloud_backup.providers.aliyundrive import split_remote_path as split_aliyun_path
from cloud_backup.providers.pan123 import split_remote_path as split_pan123_path


def test_local_folder_backup_uploads_once_and_skips_generated_files(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    (source / "photo.jpg").write_bytes(b"photo-data")
    (source / "clip.mp4").write_bytes(b"video-data")
    (source / "bracket_project.prj").write_text("generated", encoding="utf-8")
    (source / ".photo_share_cache").mkdir()
    (source / ".photo_share_cache" / "cached.jpg").write_bytes(b"cache")
    engine = configured_engine(source, target)
    services = SimpleNamespace(roots={"root1": source})

    engine._run = engine._new_run_locked(manual=True)
    engine._execute_run(services)

    assert engine._run["state"] == "ready"
    assert engine._run["uploaded"] == 2
    assert (target / "cold" / "root1" / "photo.jpg").read_bytes() == b"photo-data"
    assert (target / "cold" / "root1" / "clip.mp4").read_bytes() == b"video-data"
    assert not (target / "cold" / "root1" / "bracket_project.prj").exists()
    assert not (target / "cold" / "root1" / ".photo_share_cache" / "cached.jpg").exists()

    engine._run = engine._new_run_locked(manual=True)
    engine._execute_run(services)

    assert engine._run["state"] == "ready"
    assert engine._run["uploaded"] == 0
    assert engine._run["skipped"] == 2


def test_local_backup_target_inside_gallery_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = source / "backup"
    source.mkdir()
    (source / "photo.jpg").write_bytes(b"photo-data")
    engine = configured_engine(source, target)
    services = SimpleNamespace(roots={"root1": source})

    engine._run = engine._new_run_locked(manual=True)
    engine._execute_run(services)

    assert engine._run["state"] == "error"
    assert "不能放在图库目录里面" in engine._run["error"]


def test_cloud_provider_settings_keep_secrets_when_form_is_blank() -> None:
    current = normalize_settings({
        "provider": "aliyundrive",
        "aliyunClientSecret": "old-secret",
        "aliyunRefreshToken": "old-refresh",
        "pan123ClientSecret": "pan-secret",
    })

    updated = normalize_settings(merge_settings_update(current, {
        "aliyunClientSecret": "",
        "aliyunRefreshToken": "",
        "pan123ClientSecret": "",
        "aliyunClientId": "client-id",
    }))

    assert updated["aliyunClientSecret"] == "old-secret"
    assert updated["aliyunRefreshToken"] == "old-refresh"
    assert updated["pan123ClientSecret"] == "pan-secret"
    assert updated["aliyunClientId"] == "client-id"
    exposed = public_settings(updated)
    assert exposed["hasAliyunClientSecret"] is True
    assert exposed["hasAliyunRefreshToken"] is True
    assert exposed["hasPan123ClientSecret"] is True
    assert "aliyunClientSecret" not in exposed
    assert "pan123ClientSecret" not in exposed


def test_cloud_providers_are_available() -> None:
    providers = {item["key"]: item for item in provider_summaries()}

    assert providers["local_folder"]["available"] is True
    assert providers["aliyundrive"]["available"] is True
    assert providers["pan123"]["available"] is True
    assert providers["aliyundrive"]["planned"] is False
    assert providers["pan123"]["planned"] is False


def test_cloud_remote_paths_are_sanitized() -> None:
    assert split_aliyun_path("cold/../root1\\photo.jpg") == ["cold", "root1", "photo.jpg"]
    assert split_pan123_path("/cold/./root1/photo.jpg") == ["cold", "root1", "photo.jpg"]


def configured_engine(source: Path, target: Path) -> CloudBackupEngine:
    engine = CloudBackupEngine()
    engine._settings = {
        "enabled": True,
        "provider": "local_folder",
        "targetDir": str(target),
        "remotePrefix": "cold",
        "intervalHours": 24,
        "maxFilesPerRun": 0,
        "checksum": "size_mtime",
    }
    engine._manifest = {"version": 1, "files": {}, "runs": []}
    engine._services = SimpleNamespace(roots={"root1": source})
    return engine
