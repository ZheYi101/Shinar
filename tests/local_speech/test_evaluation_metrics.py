import math

import pytest

from shinar.local_speech.evaluation_metrics import (
    aggregate_accuracy,
    distribution,
    edit_counts,
    error_metrics,
    first_output_distribution,
    normalized_characters,
    normalized_words,
    immediate_playback_gaps,
)


def test_normalization_preserves_content_and_orthographic_differences():
    assert normalized_characters("ＡI，今日は ２ 人。") == "ai今日は2人"
    assert normalized_characters("二人") != normalized_characters("2人")
    assert normalized_characters("東京") != normalized_characters("とうきょう")
    assert normalized_words("It’s a book—really!") == ["it's", "a", "book", "really"]


def test_edit_counts_distinguish_insertions_deletions_and_substitutions():
    counts = edit_counts("abcd", "axcdz")
    assert counts == {
        "errors": 2,
        "substitutions": 1,
        "deletions": 0,
        "insertions": 1,
        "reference_units": 4,
        "hypothesis_units": 5,
    }
    assert edit_counts("abc", "")["deletions"] == 3
    assert edit_counts("", "ab")["insertions"] == 2


def test_accuracy_empty_recognition_is_a_failure_and_errors_can_exceed_one():
    assert error_metrics("你好", "", "zh")["cer"] == 1
    assert error_metrics("a", "abc", "en")["cer"] == 2
    with pytest.raises(ValueError, match="reference"):
        error_metrics("...", "text", "en")


def test_english_wer_and_cer_are_distinct():
    result = error_metrics("a long sentence", "a wrong sentence", "en")
    assert result["wer"] == pytest.approx(1 / 3)
    assert result["cer"] != result["wer"]
    assert "wer" not in error_metrics("これは本", "これは本", "ja")


def test_accuracy_uses_micro_average_and_excludes_repeated_timings_from_corpus():
    rows = [
        {"accuracy": error_metrics("a", "x", "en")},
        {"accuracy": error_metrics("abcdefghij", "abcdefghij", "en")},
    ]
    assert aggregate_accuracy(rows)["cer"] == pytest.approx(1 / 11)
    assert aggregate_accuracy(rows)["utterances"] == 2


def test_distribution_preserves_slow_tail_and_reports_sample_size():
    result = distribution(list(range(1, 21)) + [999])
    assert result == {"n": 21, "min": 1, "p50": 11, "p95": 20, "max": 999}
    assert distribution([])["p95"] is None


@pytest.mark.parametrize("value", [-1, math.inf, math.nan])
def test_distribution_rejects_invalid_samples(value):
    with pytest.raises(ValueError):
        distribution([value])


def test_fast_first_pcm_does_not_hide_later_playback_starvation():
    result = immediate_playback_gaps(
        [{"ms": 100, "samples": 2400}, {"ms": 400, "samples": 2400}], 24000
    )
    assert result["max_gap_ms"] == 200
    assert result["total_gap_ms"] == 200
    assert result["gaps"] == 1
    assert not immediate_playback_gaps([], 24000)["observed"]
    assert immediate_playback_gaps([{"ms": 100, "samples": 24000}], 24000)["gaps"] == 0


def test_first_output_percentiles_keep_failures_in_population():
    result = first_output_distribution(list(range(1, 50)) + [None])
    assert result["attempts"] == 50 and result["missing"] == 1
    assert result["successful_only"]["p95"] == 47
    assert result["p95"] == 48
    failed = first_output_distribution(list(range(1, 48)) + [None] * 3)
    assert failed["p50"] == 25
    assert failed["p95"] is None
    assert failed["p95_unavailable_due_to_missing"]
    assert first_output_distribution([None] * 50)["p50"] is None
    assert first_output_distribution([])["attempts"] == 0
