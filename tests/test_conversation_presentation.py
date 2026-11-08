"""Display identity, immutable snapshots and facade side-effect regressions."""

from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace

import pytest

from shinar.desktop.conversation_presentation import (
    ConversationEvent, ConversationPresentation, PresentationToken, display_value,
)
from shinar.desktop.conversation_view import ConversationView


def token(generation=1, task="job", turn="turn"):
    return PresentationToken("session", turn, generation, 0, task)


@pytest.mark.parametrize("kind", [
    "begin", "confirm", "delta", "complete", "fail", "interrupt", "settled",
    "refresh", "preview", "recording", "timing", "error", "invalidate",
])
def test_old_events_cannot_change_a_retry_of_the_same_turn(kind):
    view = ConversationPresentation()
    old, retry = token(), token(2, "retry")
    assert view.apply(ConversationEvent("begin", old))
    assert view.apply(ConversationEvent("begin", retry))
    assert view.apply(ConversationEvent("delta", retry, text="current reply"))
    before = view.snapshot
    assert not view.apply(ConversationEvent(kind, old, text="obsolete", seconds=99), [{"id": "old"}])
    assert view.snapshot is before


def test_snapshot_and_nested_messages_are_read_only_and_qt_values_are_detached():
    view = ConversationPresentation()
    original = [{"content": "confirmed", "source": {"spans": [{"start": 3}]}}]
    view.apply(ConversationEvent("refresh"), original)
    original[0]["content"] = "changed outside"
    snapshot = view.snapshot
    with pytest.raises(FrozenInstanceError):
        snapshot.streaming_text = "bypass"
    with pytest.raises(TypeError):
        snapshot.messages[0]["source"]["spans"][0]["start"] = 9
    qml = display_value(snapshot.messages)
    qml[0]["source"]["spans"][0]["start"] = 99
    assert snapshot.messages[0]["content"] == "confirmed"
    assert snapshot.messages[0]["source"]["spans"][0]["start"] == 3


@pytest.mark.parametrize("end", ["complete", "fail", "interrupt", "invalidate", "settled"])
def test_terminal_events_discard_half_stream_and_reject_further_deltas(end):
    view, identity = ConversationPresentation(), token()
    view.apply(ConversationEvent("refresh"), [{"role": "user", "content": "sent"}])
    view.apply(ConversationEvent("begin", identity))
    view.apply(ConversationEvent("delta", identity, text="unfinished half"))
    assert view.apply(ConversationEvent(end, identity))
    assert view.snapshot.streaming_text == ""
    assert display_value(view.snapshot.messages) == [{"role": "user", "content": "sent"}]
    assert not view.apply(ConversationEvent("delta", identity, text="late half"))


class SignalLog:
    def __init__(self):
        self.calls = 0

    def emit(self):
        self.calls += 1


class DisplayHarness(ConversationView):
    def __init__(self):
        self._conversation = ConversationPresentation()
        self._presentation_generation = 0
        self._closed = False
        self._workbench = SimpleNamespace(
            session=SimpleNamespace(id="session", messages=[], feedback_items=[])
        )
        self._draft, self._revision = "sent draft", 0
        for name in ("messagesChanged", "historyChanged", "messageSent", "uiChanged", "busyChanged"):
            setattr(self, name, SignalLog())

    @property
    def draft_revision(self):
        return self._revision

    @property
    def draft(self):
        return self._draft

    @draft.setter
    def draft(self, text):
        self._revision += 1
        self._draft = text

    def restore_last_reply(self):
        pass


def begin(view, task="job"):
    identity = view.new_presentation_token(task)
    assert view.present_conversation(ConversationEvent("begin", identity))
    return identity


@pytest.mark.parametrize("edit_new_draft", [False, True])
def test_confirmation_clears_only_the_sent_version_and_typing_does_not_reject_reply(edit_new_draft):
    view = DisplayHarness()
    identity = begin(view)
    sent = (view.draft_revision, view.draft)
    if edit_new_draft:
        view.draft = "next thought"
    confirmed = view.confirm_presentation(identity, "turn", view._workbench.session, sent)
    assert view.draft == ("next thought" if edit_new_draft else "")
    assert view.present_conversation(ConversationEvent("delta", confirmed, text="valid reply"))
    assert view.presentation.streaming_text == "valid reply"
    assert view.historyChanged.calls == 1


@pytest.mark.parametrize("kind", ["confirm", "complete", "fail", "interrupt", "refresh", "settled"])
def test_late_events_cannot_clear_new_draft_project_history_or_emit_signals(kind):
    view = DisplayHarness()
    old = begin(view)
    current = begin(view, "retry")
    view.draft = "new draft"
    view.present_conversation(ConversationEvent("delta", current, text="current reply"))
    before, signals = view.presentation, (view.uiChanged.calls, view.messagesChanged.calls)
    obsolete = replace(old, turn_id="old-turn") if kind == "confirm" else old
    assert not view.present_conversation(ConversationEvent(
        kind, obsolete, sent_draft=(view.draft_revision, view.draft),
        history_changed=True, message_sent=True,
    ))
    assert view.presentation is before and view.draft == "new draft"
    assert (view.uiChanged.calls, view.messagesChanged.calls) == signals
    assert not view.messageSent.calls and not view.historyChanged.calls


def test_history_switch_and_shutdown_invalidate_every_old_event():
    view = DisplayHarness()
    old = begin(view)
    view.present_conversation(ConversationEvent("invalidate"))
    view._workbench.session = SimpleNamespace(id="history", messages=[], feedback_items=[])
    view.present_conversation(ConversationEvent("refresh"))
    assert not view.present_conversation(ConversationEvent("complete", old))
    current = begin(view, "history-job")
    view.present_conversation(ConversationEvent("invalidate"))
    view._closed = True
    before = view.presentation
    for kind in ("begin", "confirm", "complete", "delta", "error", "refresh", "status"):
        assert not view.present_conversation(ConversationEvent(kind, current))
    assert view.presentation is before


def test_settlement_is_idempotent_and_only_emits_message_sent_once():
    view = DisplayHarness()
    identity = begin(view)
    event = ConversationEvent("settled", identity, history_changed=True, message_sent=True)
    assert view.present_conversation(event)
    assert not view.present_conversation(event)
    assert view.messageSent.calls == view.historyChanged.calls == 1


def test_duplicate_confirmation_does_not_clear_stream_or_a_new_draft():
    view = DisplayHarness()
    identity = begin(view)
    event = ConversationEvent(
        "confirm", replace(identity, turn_id="turn"),
        sent_draft=(view.draft_revision, view.draft), history_changed=True,
    )
    assert view.present_conversation(event)
    view.present_conversation(ConversationEvent("delta", event.token, text="already streaming"))
    view.draft = "next thought"
    before = view.presentation
    assert not view.present_conversation(event)
    assert view.presentation is before and view.draft == "next thought"
    assert view.historyChanged.calls == 1
