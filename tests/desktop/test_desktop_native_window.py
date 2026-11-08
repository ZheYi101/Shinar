"""The hidden Windows probe verifies HWND styles, never pointer/DPI behaviour."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.skipif(os.name != "nt" or importlib.util.find_spec("PySide6") is None,
                    reason="Requires native Windows Qt runtime")

def test_hidden_windows_window_has_no_native_caption():
    result = subprocess.run([sys.executable, "scripts/check_desktop_window.py"],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(next(line for line in result.stdout.splitlines() if line.startswith("{")))
    assert report["platform"] == "windows"
    assert not report["visible"] and not report["native_caption"]
