"""Detached feedback and review DTOs; never writes learning sessions."""

from dataclasses import dataclass, replace
from shinar.desktop.presentation.conversation_presentation import freeze


@dataclass(frozen=True)
class ReviewSnapshot:
    feedback: tuple = ()
    reviews: tuple = ()


class ReviewProjection:
    def __init__(self):
        self._snapshot = ReviewSnapshot()

    @property
    def snapshot(self) -> ReviewSnapshot:
        return self._snapshot

    def feedback(self, items) -> None:
        self._snapshot = replace(self._snapshot, feedback=freeze(items))

    def reviews(self, items) -> None:
        self._snapshot = replace(self._snapshot, reviews=freeze(items))
