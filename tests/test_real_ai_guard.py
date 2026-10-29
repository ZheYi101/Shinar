"""Exercise opt-in policy without creating a provider or calling a service."""

from pathlib import Path

import pytest

pytest_plugins = ["pytester"]


@pytest.mark.parametrize(
    ("enabled_env", "enabled_option", "passed", "skipped"),
    [
        ("0", False, 1, 1),
        ("1", False, 1, 1),
        ("0", True, 1, 1),
        ("1", True, 2, 0),
    ],
)
def test_paid_tests_require_both_opt_ins(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    enabled_env: str,
    enabled_option: bool,
    passed: int,
    skipped: int,
) -> None:
    monkeypatch.setenv("RUN_REAL_AI_TESTS", enabled_env)
    pytester.makeconftest(Path(__file__).with_name("conftest.py").read_text(encoding="utf-8"))
    pytester.makeini("[pytest]\nmarkers = real_ai: synthetic paid test\n")
    pytester.makepyfile(
        """
        import pytest

        def test_offline():
            pass

        @pytest.mark.real_ai
        def test_paid_standin():
            pass
        """
    )
    options = ["--run-real-ai"] if enabled_option else []
    result = pytester.runpytest_subprocess("-q", *options)
    result.assert_outcomes(passed=passed, skipped=skipped)
