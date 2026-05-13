from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

PLUGIN_PARENT = Path(__file__).resolve().parents[1] / "plugins"
if str(PLUGIN_PARENT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_PARENT))

from cloud_backup.engine import CloudBackupEngine


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


def configured_engine(source: Path, target: Path) -> CloudBackupEngine:
    engine = CloudBackupEngine()
    engine._settings = {
        "enabled": True,
        "provider": "local_folder",
        "targetDir": str(target),
        "remotePrefix": "cold",
        "intervalHours": 24,
        "maxFilesPerRun": 0,
        "checksum": "sha256",
    }
    engine._manifest = {"version": 1, "files": {}, "runs": []}
    engine._services = SimpleNamespace(roots={"root1": source})
    return engine
