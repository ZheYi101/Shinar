"""Standalone probes retain imports and release scenarios after failed assertions."""

import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.support.desktop import desktop_scene

ROOT = Path(__file__).resolve().parents[2]


def test_scenario_failure_closes_every_owned_service(qt_app, tmp_path):
    class ProbeFailure(Exception):
        pass

    original = os.environ.get("SHINAR_KIRIGAMI_MODE")
    with pytest.raises(ProbeFailure):
        with desktop_scene(qt_app, tmp_path) as scene:
            vm, window, _, _, _, audio, _ = scene
            workspace = window.property("workspaceController")
            raise ProbeFailure()
    assert not vm._worker._thread or not vm._worker._thread.is_alive()
    assert audio.cleared and workspace.navigation_snapshot.closed
    assert os.environ.get("SHINAR_KIRIGAMI_MODE") == original


@pytest.mark.parametrize("name", [
    "validate_continuous_desktop", "validate_continuous_playback",
    "validate_voice_readiness", "validate_voice_handoff", "validate_reader_workspace",
    "validate_desktop_lifecycle", "validate_speech_download_ui",
])
def test_validation_command_imports_using_public_modules(name, tmp_path):
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / (name + ".py")), "--help"],
        cwd=tmp_path, capture_output=True, text=True, timeout=30,
        env={**os.environ, "RUN_REAL_AI_TESTS": "0", "QT_QPA_PLATFORM": "offscreen"},
    )
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout.lower()
