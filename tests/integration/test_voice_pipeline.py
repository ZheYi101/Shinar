"""Opt-in tests intentionally fail, rather than silently mock missing resources."""

import json
from pathlib import Path
import sys

import pytest

from lingualoop.local_speech.processes import run_owned

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.local_speech_integration
@pytest.mark.parametrize("case", ["zh", "en", "ja", "ja_reazon", "en_melo"])
def test_actual_local_speech_pipeline(request, case):
    run_case(request, case, False)


@pytest.mark.local_speech_integration
@pytest.mark.realtime_integration
@pytest.mark.parametrize("case", ["zh", "en", "ja"])
def test_actual_rtc_wav_and_speech_pipeline(request, case):
    run_case(request, case, True)


def run_case(request, case, rtc):
    config = Path(request.config.getoption("--speech-config")).resolve()
    assert config.is_file(), (
        f"Prepare explicit offline profiles at {config}; see docs/desktop/VOICE_PYTHON.md"
    )
    output = ROOT / "build/voice-python-integration" / ("rtc" if rtc else "local") / f"{case}.json"
    command = [
        sys.executable,
        str(ROOT / "scripts/validate_voice_pipeline.py"),
        "--config",
        str(config),
        "--case",
        case,
        "--output",
        str(output),
    ]
    if rtc:
        command.append("--rtc")
    response = run_owned(command, timeout=240)
    assert output.is_file(), f"Integration process exited {response.returncode} without report"
    report = json.loads(output.read_text(encoding="utf-8"))
    assert response.returncode == 0 and report.get("passed"), report


@pytest.mark.realtime_integration
def test_actual_rtc_transport_with_owned_stun():
    from lingualoop.realtime.local_server import owned_rfc1918_addresses

    address = next(iter(sorted(owned_rfc1918_addresses())), "127.0.0.1")
    output = ROOT / "build/livekit-probe/pytest-python-integration.json"
    response = run_owned(
        [
            sys.executable,
            str(ROOT / "scripts/probe_livekit.py"),
            "--rtc-bind-ip",
            address,
            "--output",
            str(output),
        ],
        timeout=90,
    )
    assert output.is_file()
    report = json.loads(output.read_text(encoding="utf-8"))
    assert response.returncode == 0 and report.get("passed"), {
        key: report.get(key)
        for key in ("phase", "error_code", "child_stages", "rtc_child_exit_code")
    }
