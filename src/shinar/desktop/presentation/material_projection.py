"""Material/topic choices and preparation observation; source truth stays in Workbench."""

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class MaterialSnapshot:
    selected_topic: str = ""
    custom_topic: str = ""
    practice_mode: str = "discussion"
    role_description: str = ""
    topic_filter: str = ""
    topic_search: str = ""
    preparation_state: str = "idle"
    analysis_identity: tuple[str, int] | None = None


class MaterialProjection:
    def __init__(self, all_topics: str):
        self._snapshot = MaterialSnapshot(topic_filter=all_topics)

    @property
    def snapshot(self) -> MaterialSnapshot:
        return self._snapshot

    def topic(self, value: str) -> None:
        self._snapshot = replace(self._snapshot, selected_topic=value)

    def custom(self, value: str) -> None:
        self._snapshot = replace(self._snapshot, custom_topic=value)

    def mode(self, value: str) -> None:
        if value in {"discussion", "roleplay"}:
            self._snapshot = replace(self._snapshot, practice_mode=value)

    def role(self, value: str) -> None:
        self._snapshot = replace(self._snapshot, role_description=value)

    def filter(self, value: str) -> None:
        self._snapshot = replace(self._snapshot, topic_filter=value)

    def search(self, value: str) -> None:
        self._snapshot = replace(self._snapshot, topic_search=value.strip())

    def preparation(self, value: str) -> None:
        self._snapshot = replace(self._snapshot, preparation_state=value)

    def analysis(self, value: tuple[str, int] | None) -> None:
        self._snapshot = replace(self._snapshot, analysis_identity=value)
