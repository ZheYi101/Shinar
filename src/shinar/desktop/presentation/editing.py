"""Session-local drafts and display generations, independent of Qt and persistence."""

from dataclasses import dataclass, field, replace
from typing import Mapping

from shinar.desktop.presentation.conversation_presentation import PresentationToken, freeze


@dataclass(frozen=True)
class EditorSnapshot:
    draft: str = ""
    revision: int = 0
    generation: int = 0
    last_reply: str = ""
    session_drafts: Mapping[str, str] = field(default_factory=lambda: freeze({}))


class SessionEditing:
    def __init__(self):
        self._snapshot = EditorSnapshot()

    @property
    def snapshot(self) -> EditorSnapshot:
        return self._snapshot

    def draft(self, value: str) -> bool:
        if value == self._snapshot.draft:
            return False
        self._snapshot = replace(self._snapshot, draft=value, revision=self._snapshot.revision + 1)
        return True

    def remember(self, session_id: str) -> None:
        self._snapshot = replace(
            self._snapshot,
            session_drafts=freeze(
                {**self._snapshot.session_drafts, session_id: self._snapshot.draft}
            ),
        )

    def restore(self, session_id: str) -> None:
        self.draft(self._snapshot.session_drafts.get(session_id, ""))

    def reply(self, value: str) -> None:
        self._snapshot = replace(self._snapshot, last_reply=value)

    def token(self, session_id: str, task_id: str, turn_id: str = "") -> PresentationToken:
        self._snapshot = replace(self._snapshot, generation=self._snapshot.generation + 1)
        return PresentationToken(
            session_id, turn_id, self._snapshot.generation, self._snapshot.revision, task_id
        )
