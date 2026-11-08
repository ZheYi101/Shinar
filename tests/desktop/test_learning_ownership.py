"""Draft ownership, frozen projections and identified business callbacks."""

from dataclasses import FrozenInstanceError
import pytest

from shinar.desktop.presentation.editing import SessionEditing
from shinar.desktop.presentation.operations import LearningOperations
from shinar.desktop.presentation.review_projection import ReviewProjection


def test_session_editor_keeps_drafts_and_monotonic_versions_across_history():
    state = SessionEditing()
    state.draft("first draft")
    state.remember("first")
    first = state.token("first", "send")
    state.draft("edited after send")
    assert state.snapshot.revision > first.draft_revision
    state.remember("first")
    state.restore("second")
    assert state.snapshot.draft == ""
    state.draft("second draft")
    state.remember("second")
    state.restore("first")
    assert state.snapshot.draft == "edited after send"
    assert state.token("first", "retry").generation > first.generation
    with pytest.raises(TypeError):
        state.snapshot.session_drafts["first"] = "changed"
    with pytest.raises(FrozenInstanceError):
        state.snapshot.draft = "changed"


def test_business_callback_is_bound_to_original_job_and_invalidated_on_shutdown():
    state = LearningOperations()
    callback = lambda result: None
    operation = lambda: None
    first = state.start("start", operation, callback, "session", "material")
    assert state.complete("foreign-job", "") == (False, None)
    assert state.snapshot.busy
    assert state.complete(first.task, "failed") == (True, callback)
    assert state.retry == ("start", operation, callback)
    retry = state.start(*state.retry, "session", "material")
    assert retry.generation > first.generation and retry.instance == first.instance
    assert state.complete(first.task, "") == (False, None)
    assert state.snapshot.busy
    state.close()
    assert state.complete(retry.task, "") == (False, None)
    assert not state.snapshot.retryable and state.retry is None


def test_review_projection_detaches_input_and_nested_feedback():
    state = ReviewProjection()
    original = [{"original": "said", "metadata": {"ids": ["1"]}}]
    state.feedback(original)
    original[0]["metadata"]["ids"].append("new")
    assert state.snapshot.feedback[0]["metadata"]["ids"] == ("1",)
    with pytest.raises(TypeError):
        state.snapshot.feedback[0]["metadata"]["ids"][0] = "changed"
