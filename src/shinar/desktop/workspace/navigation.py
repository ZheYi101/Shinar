"""Routes, tree projection and editor restoration; no reader or import state."""

from dataclasses import dataclass, field, replace
from typing import Any

from shinar.desktop.presentation.conversation_presentation import freeze


@dataclass(frozen=True)
class NavigationSnapshot:
    route: str
    browsing: str
    category: str = "appearance"
    collapsed: bool = False
    expanded: frozenset[str] = frozenset()
    materials: tuple = ()
    threads: tuple = ()
    cursor: int = 0
    scroll: float = 0.0
    opening: Any = field(default_factory=lambda: freeze({}))
    positions: Any = field(default_factory=lambda: freeze({}))
    error: str = ""
    closed: bool = False


class WorkspaceNavigation:
    def __init__(self, route, browsing, collapsed):
        self._snapshot = NavigationSnapshot(
            route,
            browsing,
            collapsed=collapsed,
            expanded=frozenset({browsing}) if browsing else frozenset(),
        )

    @property
    def snapshot(self):
        return self._snapshot

    def route(self, value):
        self._snapshot = replace(self._snapshot, route=value, error="")

    def browse(self, value):
        self._snapshot = replace(self._snapshot, browsing=value)

    def expand(self, value):
        self._snapshot = replace(self._snapshot, expanded=self._snapshot.expanded | {value})

    def toggle(self, value):
        self._snapshot = replace(self._snapshot, expanded=self._snapshot.expanded ^ {value})

    def category(self, value):
        self._snapshot = replace(self._snapshot, category=value)

    def collapse(self):
        self._snapshot = replace(self._snapshot, collapsed=not self._snapshot.collapsed)

    def models(self, threads, materials):
        threads, materials = freeze(threads), freeze(materials)
        changed = (threads, materials) != (self._snapshot.threads, self._snapshot.materials)
        self._snapshot = replace(self._snapshot, threads=threads, materials=materials)
        return changed

    def editor(self, cursor, scroll):
        self._snapshot = replace(self._snapshot, cursor=cursor, scroll=scroll)

    def remember(self, identity):
        self._snapshot = replace(
            self._snapshot,
            positions=freeze(
                {
                    **self._snapshot.positions,
                    identity: (self._snapshot.cursor, self._snapshot.scroll),
                }
            ),
        )

    def restore(self, identity, cursor):
        self.editor(*self._snapshot.positions.get(identity, (cursor, 0.0)))

    def opening(self, value):
        self._snapshot = replace(
            self._snapshot,
            opening=freeze({**self._snapshot.opening, self._snapshot.browsing: value}),
        )

    def take_opening(self):
        value = self._snapshot.opening.get(self._snapshot.browsing, "")
        remaining = dict(self._snapshot.opening)
        remaining.pop(self._snapshot.browsing, None)
        self._snapshot = replace(self._snapshot, opening=freeze(remaining))
        return value

    def error(self, value):
        self._snapshot = replace(self._snapshot, error=str(value))

    def close(self):
        self._snapshot = replace(self._snapshot, closed=True)
