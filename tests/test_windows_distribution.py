"""Distribution boundaries: config lookup, icon decoding and private-file rejection."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import struct

import pytest

from shinar.desktop.packaged import configuration_file

ROOT = Path(__file__).resolve().parents[1]


def build_module():
    spec = importlib.util.spec_from_file_location(
        "build_windows", ROOT / "scripts/build_windows.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_user_config_location_and_explicit_override(monkeypatch, tmp_path):
    for key in ("SHINAR_CONFIG_FILE", "LINGUALOOP_CONFIG_FILE", "SHINAR_DATA_DIR", "LINGUALOOP_DATA_DIR"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert configuration_file() == tmp_path / "Shinar/.env"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SHINAR_CONFIG_FILE", "custom/model.env")
    assert configuration_file() == tmp_path / "custom/model.env"


@pytest.mark.parametrize(
    "name", [".env", ".ENV.production", "ai-services.json", "user.sqlite3", "user.sqlite3-wal", "requests.log"]
)
def test_payload_rejects_private_files(tmp_path, name):
    (tmp_path / name).write_text("private", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Private data is not distributable"):
        build_module().inspect_payload(tmp_path)


def test_payload_allows_example_and_includes_hashes(tmp_path):
    (tmp_path / ".env.example").write_bytes(b"OPENAI_API_KEY=\n")
    report = build_module().inspect_payload(tmp_path)
    assert len(report["files"]) == 1
    assert len(report["files"][0]["sha256"]) == 64
    assert report["total_bytes"] == 16


def test_windows_icon_contains_decodable_sizes():
    pytest.importorskip("PySide6")
    from PySide6.QtGui import QImage

    icon = (ROOT / "src/shinar/desktop/assets/app-icon.ico").read_bytes()
    reserved, kind, count = struct.unpack_from("<HHH", icon)
    assert (reserved, kind, count) == (0, 1, 9)
    sizes = []
    for index in range(count):
        width, height, _, _, planes, bits, length, offset = struct.unpack_from(
            "<BBBBHHII", icon, 6 + index * 16
        )
        width, height = width or 256, height or 256
        frame = QImage.fromData(icon[offset : offset + length], "PNG")
        assert not frame.isNull()
        assert (frame.width(), frame.height(), planes, bits) == (width, height, 1, 32)
        sizes.append(width)
    assert sizes == [16, 20, 24, 32, 40, 48, 64, 128, 256]


def test_identity_module_does_not_eagerly_import_qt():
    # Importing metadata/resources must remain safe for headless CLI installations.
    import subprocess
    import sys

    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import shinar.desktop.shell.identity; assert 'PySide6.QtGui' not in sys.modules",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        timeout=10,
    )
    assert probe.returncode == 0, probe.stderr
