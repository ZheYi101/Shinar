"""Shared test policy: ordinary regression runs never opt into paid AI calls."""

import os

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-real-ai",
        action="store_true",
        default=False,
        help="Enable real_ai tests only when RUN_REAL_AI_TESTS=1 is also set.",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-real-ai") and os.getenv("RUN_REAL_AI_TESTS", "").strip() == "1":
        return
    skip = pytest.mark.skip(reason="Real AI tests require --run-real-ai and RUN_REAL_AI_TESTS=1.")
    for item in items:
        if item.get_closest_marker("real_ai") is not None:
            item.add_marker(skip)
