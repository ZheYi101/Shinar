"""Shared test policy: ordinary regression runs never opt into paid AI calls."""

import os

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--run-local-speech", action="store_true", default=False,
                     help="Run real, offline local speech model integrations.")
    parser.addoption("--run-realtime", action="store_true", default=False,
                     help="Run real local LiveKit transport integrations.")
    parser.addoption("--speech-config", default="build/voice-python-integration/config.json",
                     help="Explicit prepared model configuration for local integrations.")
    parser.addoption(
        "--run-real-ai",
        action="store_true",
        default=False,
        help="Enable real_ai tests only when RUN_REAL_AI_TESTS=1 is also set.",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    allow_real_ai = config.getoption("--run-real-ai") and os.getenv("RUN_REAL_AI_TESTS", "").strip() == "1"
    skip = pytest.mark.skip(reason="Real AI tests require --run-real-ai and RUN_REAL_AI_TESTS=1.")
    for item in items:
        if item.get_closest_marker("real_ai") is not None and not allow_real_ai:
            item.add_marker(skip)
        for marker, option in (("local_speech_integration", "--run-local-speech"),
                               ("realtime_integration", "--run-realtime")):
            if item.get_closest_marker(marker) and not config.getoption(option):
                item.add_marker(pytest.mark.skip(reason=f"Explicit {option} is required."))
