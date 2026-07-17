from __future__ import annotations

import os
from pathlib import Path

import pytest

from desktop_client import build_config
from desktop_client.windows_app import (
    STARTUP_TIMEOUT_SECONDS,
    BackendRunner,
    SingleInstance,
    application_data_root,
)
from utils.passwords import password_hash, verify_password_hash


def test_local_password_hash_uses_scrypt_and_random_salt():
    first = password_hash("a sufficiently long password")
    second = password_hash("a sufficiently long password")
    assert first.startswith("scrypt$")
    assert second.startswith("scrypt$")
    assert first != second
    assert verify_password_hash("a sufficiently long password", first)
    assert not verify_password_hash("wrong password", first)


def test_legacy_password_hash_is_still_verifiable():
    import hashlib

    legacy = hashlib.sha256(b"legacy password").hexdigest()
    assert verify_password_hash("legacy password", legacy)
    assert not verify_password_hash("wrong", legacy)


def test_windows_data_root_uses_local_app_data(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert application_data_root() == tmp_path / "xianyuxian"


def test_data_root_requires_local_app_data(monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    with pytest.raises(RuntimeError, match="LOCALAPPDATA"):
        application_data_root()


def test_non_windows_single_instance_is_a_noop():
    if os.name == "nt":
        pytest.skip("covered by the packaged Windows self-test")
    instance = SingleInstance()
    assert instance.acquire() is True
    instance.release()


def test_packaged_backend_allows_slow_windows_cold_start():
    assert STARTUP_TIMEOUT_SECONDS >= 120


def test_backend_timeout_writes_actionable_diagnostic(tmp_path: Path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    runner = BackendRunner(log_dir)

    detail = runner.failure_detail(STARTUP_TIMEOUT_SECONDS)

    assert "当前阶段" in detail
    assert str(runner.error_log_path) in detail
    diagnostic = runner.error_log_path.read_text(encoding="utf-8")
    assert "phase=等待启动" in diagnostic
    assert "thread_alive=False" in diagnostic


def test_packaged_backend_uses_static_fastapi_import():
    project_root = Path(__file__).resolve().parents[2]
    start_source = (project_root / "Start.py").read_text(encoding="utf-8")
    spec_source = (project_root / "packaging" / "windows" / "xianyuxian.spec").read_text(encoding="utf-8")
    launcher_source = (project_root / "desktop_client" / "windows_app.py").read_text(encoding="utf-8")

    assert "from reply_server import app" in start_source
    assert "config = uvicorn.Config(" in start_source
    assert "log_config=None" in start_source
    assert '"reply_server"' in spec_source
    assert '"desktop-console.log"' in launcher_source


def test_production_license_trust_root_is_embedded():
    assert build_config.LICENSE_API_BASE_URL == "https://xianyuxian.dskjahf.xyz"
    assert build_config.LICENSE_PUBLIC_KEY_BASE64 == "PZiG1O-uIWneaA4sYpi9SUQUhYbeA7nf9DVjyEdEwYE"
