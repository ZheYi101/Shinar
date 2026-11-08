"""Explicit, dependency-free metrics for public-corpus speech evaluations."""

from __future__ import annotations

import math
import unicodedata
from collections.abc import Sequence


def normalized_characters(text: str) -> str:
    """NFKC/casefold; retain letters and numbers, including Japanese kana/kanji."""
    return "".join(
        char
        for char in unicodedata.normalize("NFKC", text).casefold()
        if unicodedata.category(char)[0] in {"L", "N"}
    )


def normalized_words(text: str) -> list[str]:
    """English WER tokens; punctuation becomes boundaries, apostrophes are retained."""
    text = unicodedata.normalize("NFKC", text).casefold().replace("’", "'")
    return "".join(char if char.isalnum() or char == "'" else " " for char in text).split()


def edit_counts(reference: Sequence, hypothesis: Sequence) -> dict[str, int]:
    """Levenshtein S/D/I with deterministic substitution/deletion/insertion ties."""
    # Rows contain distance, substitutions, deletions, insertions. Linear memory.
    previous = [(i, 0, 0, i) for i in range(len(hypothesis) + 1)]
    for row, ref in enumerate(reference, 1):
        current = [(row, 0, row, 0)]
        for col, hyp in enumerate(hypothesis, 1):
            distance, subs, deletes, inserts = previous[col - 1]
            replace = (distance + (ref != hyp), subs + (ref != hyp), deletes, inserts)
            distance, subs, deletes, inserts = previous[col]
            delete = (distance + 1, subs, deletes + 1, inserts)
            distance, subs, deletes, inserts = current[col - 1]
            insert = (distance + 1, subs, deletes, inserts + 1)
            current.append(min((replace, delete, insert), key=lambda value: value[0]))
        previous = current
    distance, subs, deletes, inserts = previous[-1]
    return {
        "errors": distance,
        "substitutions": subs,
        "deletions": deletes,
        "insertions": inserts,
        "reference_units": len(reference),
        "hypothesis_units": len(hypothesis),
    }


def error_metrics(reference: str, hypothesis: str, language: str) -> dict:
    chars = normalized_characters(reference)
    if not chars:
        raise ValueError("Accuracy requires a nonempty reference.")
    result = {"characters": edit_counts(chars, normalized_characters(hypothesis))}
    result["cer"] = result["characters"]["errors"] / len(chars)
    if language == "en":
        words = normalized_words(reference)
        result["words"] = edit_counts(words, normalized_words(hypothesis))
        result["wer"] = result["words"]["errors"] / len(words)
    return result


def distribution(values: list[float]) -> dict:
    """Nearest-rank quantiles; preserve sample size, minimum and worst observation."""
    if not values:
        return {"n": 0, "min": None, "p50": None, "p95": None, "max": None}
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("Timing and rate samples must be finite and nonnegative.")
    ordered = sorted(values)
    return {
        "n": len(values),
        "min": ordered[0],
        "p50": ordered[math.ceil(len(values) * 0.5) - 1],
        "p95": ordered[math.ceil(len(values) * 0.95) - 1],
        "max": ordered[-1],
    }


def aggregate_accuracy(rows: list[dict]) -> dict:
    """Micro average by reference units, never averaging sentence error rates."""
    result = {"utterances": len(rows)}
    for field, metric in (("characters", "cer"), ("words", "wer")):
        counts = [row["accuracy"][field] for row in rows if field in row["accuracy"]]
        if counts:
            totals = {key: sum(row[key] for row in counts) for key in counts[0]}
            result[field] = totals
            result[metric] = totals["errors"] / totals["reference_units"]
    return result


def first_output_distribution(values: list[float | None]) -> dict:
    """Absent output is a service failure beyond finite observations, not zero ms."""
    successful = [value for value in values if value is not None]
    observed = distribution(successful)
    ordered = sorted(successful)
    result = {
        "attempts": len(values),
        "successes": len(successful),
        "missing": len(values) - len(successful),
        "successful_only": observed,
    }
    for label, quantile in (("p50", 0.5), ("p95", 0.95)):
        rank = math.ceil(len(values) * quantile)
        result[label] = ordered[rank - 1] if 0 < rank <= len(ordered) else None
    result["p95_unavailable_due_to_missing"] = bool(values) and result["p95"] is None
    return result


def immediate_playback_gaps(callbacks: list[dict], sample_rate: int) -> dict:
    """Ideal consumer starts at first PCM; simulation excludes device/RTC buffering."""
    if sample_rate <= 0:
        raise ValueError("Sample rate must be positive.")
    if not callbacks:
        return {"observed": False, "total_gap_ms": None, "max_gap_ms": None, "gaps": None}
    available_until = None
    gaps = []
    previous = -1
    for callback in callbacks:
        arrival, samples = callback["ms"], callback["samples"]
        if arrival < previous or samples < 0:
            raise ValueError("Invalid PCM callback sequence.")
        previous = arrival
        if available_until is None:
            available_until = arrival
        gap = max(0, arrival - available_until)
        if gap:
            gaps.append(gap)
        available_until = max(available_until, arrival) + samples / sample_rate * 1000
    return {
        "observed": True,
        "total_gap_ms": sum(gaps),
        "max_gap_ms": max(gaps, default=0),
        "gaps": len(gaps),
    }
