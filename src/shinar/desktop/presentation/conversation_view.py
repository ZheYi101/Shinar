"""Main-thread conversation event entry point for the existing Qt facade."""

from dataclasses import replace

from shinar.core import PracticeSession

from shinar.desktop.presentation.conversation_presentation import (
    ConversationEvent,
    ConversationSnapshot,
    PresentationToken,
)


class ConversationViewMixin:
    @property
    def presentation(self) -> ConversationSnapshot:
        return self._conversation.snapshot

    def new_presentation_token(self, task_id: str, turn_id: str = "") -> PresentationToken:
        session = self._workbench.session
        return self._editing.token(session.id if session else "", task_id, turn_id)

    def present_conversation(self, event: ConversationEvent) -> bool:
        """Reject obsolete work before projecting messages or touching the draft."""
        if self._operations.snapshot.closed and event.kind != "invalidate":
            return False
        session = self._workbench.session
        session_id = session.id if session else ""
        if event.token is not None and event.token.session_id != session_id:
            return False
        if event.session is not None and event.session.id != session_id:
            return False
        if not self._conversation.accepts(event):
            return False
        project = event.kind in {"confirm", "complete", "fail", "interrupt", "settled", "refresh"}
        before = self.presentation
        messages = self._conversation_messages(event.session or session) if project else None
        self._conversation.apply(event, messages)
        if project:
            self._conversation_feedback(event.session or session)
            self.restore_last_reply()
        if event.kind == "confirm" and event.sent_draft == (self.draft_revision, self.draft):
            self._editing.draft("")
        if before.messages != self.presentation.messages or project:
            self.messagesChanged.emit()
        if event.history_changed:
            self.historyChanged.emit()
        if event.message_sent:
            self.messageSent.emit()
        self.uiChanged.emit()
        if event.kind == "status":
            self.busyChanged.emit()
        return True

    def confirm_presentation(
        self,
        token: PresentationToken,
        turn_id: str,
        session: PracticeSession,
        sent_draft: tuple[int, str] | None,
    ) -> PresentationToken:
        confirmed = replace(token, turn_id=turn_id)
        self.present_conversation(
            ConversationEvent(
                "confirm",
                confirmed,
                session,
                sent_draft=sent_draft,
                history_changed=True,
            )
        )
        return confirmed

    def _conversation_messages(self, session: PracticeSession | None) -> list[dict]:
        if session is None:
            return []
        turn_id, messages = "", []
        for message in session.messages:
            if message.role.value == "user":
                turn_id = message.metadata.get("turn_id", "")
            messages.append(
                {
                    **self.voice.turn_details(message, turn_id),
                    "id": message.id,
                    "role": message.role.value,
                    "content": message.content,
                    "source": message.source_context.model_dump(mode="json")
                    if message.source_context
                    else None,
                }
            )
        return messages

    def _conversation_feedback(self, session: PracticeSession | None) -> None:
        self._reviews.feedback(
            [
                {
                    "original": item.original,
                    "corrected": item.corrected,
                    "explanation": item.explanation,
                }
                for item in session.feedback_items
            ]
            if session
            else []
        )
