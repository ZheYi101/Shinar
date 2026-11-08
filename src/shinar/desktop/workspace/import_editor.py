"""Import edits and inspected-file results have one non-Qt owner."""

from dataclasses import dataclass, replace
from pathlib import Path

from shinar.core import MaterialSourceType, SubtitleCue
from shinar.core.knowledge import SourceSection
from shinar.infrastructure.material_import import ImportedMaterial
from shinar.desktop.workspace.task_identity import TaskLane


@dataclass(frozen=True)
class InspectedFile:
    title: str
    raw_content: str
    normalized_content: str
    source_type: MaterialSourceType
    source_path: str
    diagnostics: tuple[str, ...]
    cues: tuple[str, ...]
    sections: tuple[str, ...]
    epub: bytes | None

    @classmethod
    def capture(cls, value: ImportedMaterial):
        return cls(
            value.title,
            value.raw_content,
            value.normalized_content,
            value.source_type,
            value.source_path,
            tuple(value.diagnostics),
            tuple(c.model_dump_json() for c in value.subtitle_cues),
            tuple(s.model_dump_json() for s in value.source_sections),
            value.epub_content,
        )

    def material(self):
        return ImportedMaterial(
            self.title,
            self.raw_content,
            self.normalized_content,
            self.source_type,
            self.source_path,
            list(self.diagnostics),
            [SubtitleCue.model_validate_json(c) for c in self.cues],
            [SourceSection.model_validate_json(s) for s in self.sections],
            self.epub,
        )


@dataclass(frozen=True)
class ImportSnapshot:
    mode: str = "file"
    title: str = ""
    text: str = ""
    language: str = ""
    file: InspectedFile | None = None
    inspecting: bool = False
    title_version: int = 0


class ImportEditor:
    def __init__(self, language: str):
        self._snapshot = ImportSnapshot(language=language)
        self.tasks = TaskLane()

    @property
    def snapshot(self):
        return self._snapshot

    @property
    def filename(self):
        return Path(self._snapshot.file.source_path).name if self._snapshot.file else ""

    def title(self, value):
        if value != self._snapshot.title:
            self._snapshot = replace(
                self._snapshot, title=value, title_version=self._snapshot.title_version + 1
            )

    def text(self, value):
        self._snapshot = replace(self._snapshot, text=value)

    def language(self, value):
        self._snapshot = replace(self._snapshot, language=value)

    def mode(self, value):
        self._snapshot = replace(self._snapshot, mode=value)

    def inspect(self):
        previous = self._snapshot
        self._snapshot = replace(previous, file=None, inspecting=True)
        return previous

    def receive(self, value, previous):
        title = self._snapshot.title
        if self._snapshot.title_version == previous.title_version and (
            not previous.title.strip() or previous.file and previous.title == previous.file.title
        ):
            title = value.title
        self._snapshot = replace(
            self._snapshot, file=InspectedFile.capture(value), title=title, inspecting=False
        )

    def failed(self):
        self._snapshot = replace(self._snapshot, inspecting=False)

    def committed(self):
        self._snapshot = replace(self._snapshot, title="", text="", file=None)

    def close(self):
        self.tasks.close()
