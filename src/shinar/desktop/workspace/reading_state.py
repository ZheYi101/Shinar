"""Source selection and read-only projections with independent document/search tasks."""

from __future__ import annotations
import base64
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path
from secrets import token_hex
from typing import Any, Callable
from shinar.application.source_document import (
    document_paragraphs,
    python_to_utf16,
    source_hash,
    utf16_to_python,
)
from shinar.core.knowledge import SourceSpan, TurnSourceSnapshot
from shinar.core.reading_scope import reading_end
from shinar.infrastructure.blocking_jobs import BlockingRequest
from shinar.application.source_loading import SourceLoadRequest
from shinar.desktop.workspace.task_identity import TaskLane
from shinar.desktop.presentation.conversation_presentation import freeze


@dataclass(frozen=True)
class ReadingContext:
    route: str
    browsing: str


@dataclass(frozen=True)
class ReadingPosition:
    source: str | None
    opened: bool
    section: str
    scroll: float
    position: int
    material: str


@dataclass(frozen=True)
class ReadingRuntime:
    context: Callable
    material: Callable
    session: Callable
    submit: Callable
    changed: Callable
    document: Callable
    append: Callable
    selection: Callable
    reader_selection: Callable
    focus: Callable
    failed: Callable
    debounce: Callable
    asset_directory: Path
    texts: Any


class ReadingCoordinator:
    def __init__(self, runtime: ReadingRuntime):
        self.runtime = runtime
        self.document_tasks, self.search_tasks = TaskLane(), TaskLane()
        self._source_scroll, self._reader_position = 0.0, 0
        self._source_stale, self._document_ready, self._source_open = False, False, False
        self._pending_position = None
        self._source_snapshot, self._preview = None, None
        self._source_text, self._source_full = "", ""
        self._source_offset, self._source_limit = 0, 0
        self._sections, self._results = [], []
        self._source_material, self._source_end, self._source_section = "", 0, ""
        self._reader_book, self._reader_id, self._reader_error = None, "", ""
        self._reader_generation, self._reader_target = -1, None
        self._pending_search = None
        self._scope_pending, self._scope_return_route, self._scope_import_material = (
            {},
            "material",
            "",
        )
        self._positions, self._saved_current = {}, None
        self._scope_documents = {}
        self._view_mode = "current"

    @property
    def state_snapshot(self):
        return freeze(
            dict(
                section=self._source_section,
                end=self._source_end,
                target=self._reader_target,
                source_scroll=self._source_scroll,
                reader_position=self._reader_position,
                pending_search=self._pending_search,
                document_generation=self.document_tasks.generation,
                search_generation=self.search_tasks.generation,
                pending=dict(self._scope_pending),
                view=self._view_mode,
                positions={key: asdict(value) for key, value in self._positions.items()},
            )
        )

    @property
    def pendingEnd(self):
        return self._scope_pending.get(self.runtime.context().browsing, 0)

    @property
    def source_material(self):
        return self._source_material

    @property
    def source_offset(self):
        return self._source_offset

    @property
    def scope_return_route(self):
        return self._scope_return_route

    def scope_begin(self, material, return_route):
        self.preserve_current()
        self._view_mode = "scope"
        if material.id in self._scope_documents:
            self._restore_position(self._scope_documents[material.id])
        else:
            self._source_scroll, self._reader_position = 0.0, 0
        self._scope_return_route = return_route
        self._scope_pending.setdefault(material.id, reading_end(material))

    def imported(self, material_id):
        self._scope_import_material = material_id

    def scope_saved(self, material_id):
        imported = material_id == self._scope_import_material
        if imported:
            self._scope_import_material = ""
        return imported

    def mark_end(self, material_id, end):
        self._scope_pending[material_id] = end

    def show_position(self, start, end):
        self._show_position(start, end)

    def invalidate(self):
        self.document_tasks.invalidate()
        self.search_tasks.invalidate()
        self._pending_search, self._pending_position = None, None

    def close(self):
        self.document_tasks.close()
        self.search_tasks.close()
        self._pending_search = None

    def _capture(self):
        return deepcopy(
            {
                name: value
                for name, value in vars(self).items()
                if name.startswith(("_source_", "_reader_"))
                or name in {"_document_ready", "_sections", "_results", "_pending_position"}
            }
        )

    def _restore(self, record):
        for name, value in deepcopy(record).items():
            setattr(self, name, value)

    def _capture_position(self, record):
        source = record["_source_snapshot"]
        return ReadingPosition(
            source.model_dump_json() if source else None,
            record["_source_open"],
            record["_source_section"],
            record["_source_scroll"],
            record["_reader_position"],
            record["_source_material"],
        )

    def _restore_position(self, position):
        self._source_snapshot = (
            TurnSourceSnapshot.model_validate_json(position.source) if position.source else None
        )
        self._source_open, self._source_section = position.opened, position.section
        self._source_scroll, self._reader_position = position.scroll, position.position
        self._source_material = position.material

    def preserve_current(self):
        if self._saved_current is None:
            self._saved_current = self._capture()

    def restore_current(self):
        if self._view_mode == "scope":
            self._scope_documents[self._source_material] = self._capture_position(vars(self))
        if self._saved_current is not None:
            self._restore(self._saved_current)
            self._saved_current = None
        self._preview = None
        self._view_mode = "current"
        self.invalidate()

    def remember(self, session_id):
        self._positions[session_id] = self._capture_position(self._saved_current or vars(self))

    def restore(self, session_id):
        self.reset_thread()
        if session_id in self._positions:
            self._restore_position(self._positions[session_id])
        self.invalidate()

    def reset_thread(self):
        self.invalidate()
        self._saved_current, self._source_snapshot, self._preview = None, None, None
        self._source_open, self._source_section, self._source_scroll = False, "", 0.0
        self._reader_position, self._reader_book, self._reader_id = 0, None, ""
        self._document_ready = False
        self._view_mode = "current"

    @property
    def sourceOpen(self):
        return self._source_open

    def toggleSource(self):
        opened = self._source_open
        if self._source_open:
            self.document_tasks.invalidate()
            self.search_tasks.invalidate()
        self.restore_current()
        self._source_open = not opened
        if self._source_open:
            self.loadSource(self._source_section)
        else:
            self.runtime.focus()
        self.runtime.changed()

    @property
    def sourceText(self):
        return self._source_text

    @property
    def readerAvailable(self) -> bool:
        return self._reader_book is not None and (not self._reader_error) and self._document_ready

    @property
    def readerId(self) -> str:
        return self._reader_id

    @property
    def readerError(self) -> str:
        return self._reader_error

    def reader_active(self, identity: str) -> bool:
        return bool(
            identity
            and identity == self._reader_id
            and self.readerAvailable
            and (not self._source_stale)
            and (self._reader_generation == self.document_tasks.generation)
            and (
                self.runtime.context().route == "scope"
                or (self.runtime.context().route == "chat" and self._source_open)
            )
        )

    def reader_document(self, identity: str) -> dict[str, Any]:
        if not self.reader_active(identity):
            return {}
        first = self._sections[0]["start_char"] if self._sections else 0
        position = max(self._source_offset, min(self._reader_position or first, self._source_limit))
        return dict(
            identity=identity,
            epub=base64.b64encode(self._reader_book.data).decode("ascii"),
            chapters=deepcopy(self._reader_book.chapters),
            language=self.sourceLanguage,
            start=self._source_offset,
            end=self._source_limit,
            position=position,
            target=self._reader_target,
            boundary=self.pendingEnd if self.runtime.context().route == "scope" else -1,
        )

    def selectReaderRange(self, identity: str, start: int, end: int, kind: str) -> None:
        if (
            self.reader_active(identity)
            and kind in {"paragraph", "text"}
            and (self._source_offset <= start < end <= self._source_limit)
        ):
            self._select_source_range(start, end, kind)

    def saveReaderPosition(self, identity: str, position: int) -> None:
        if (
            self.reader_active(identity)
            and (not self._preview)
            and (self.runtime.context().route == "chat")
        ):
            if self._source_offset <= position <= self._source_limit:
                self._reader_position = position

    def readerFailed(self, identity: str) -> None:
        if identity == self._reader_id:
            self._reader_error = self.runtime.texts["reader_failed"]
            self.runtime.changed()

    @property
    def sections(self):
        return deepcopy(self._sections)

    @property
    def searchResults(self):
        return deepcopy(self._results)

    @property
    def historicalSource(self):
        return self._preview is not None

    @property
    def sourceStale(self):
        return self._source_stale

    @property
    def documentReady(self):
        return self._document_ready

    @property
    def sourceLanguage(self):
        material = self.runtime.material(self._source_material)
        return material.source_language.value if material else ""

    @property
    def sourceScroll(self):
        return self._source_scroll

    def saveSourceScroll(self, value: float):
        if self.runtime.context().route == "chat" and (not self._preview):
            self._source_scroll = value

    @property
    def sourceLabel(self):
        snapshot = self._preview or self._source_snapshot
        return snapshot.label if snapshot else ""

    @property
    def hasSource(self):
        return self._source_snapshot is not None

    @property
    def sourceHasMore(self):
        return self._source_offset + len(self._source_text) < self._source_limit

    def loadSource(self, section_id: str):
        scope = self.runtime.context().route == "scope"
        session = self.runtime.session()
        material_id = (
            self.runtime.context().browsing
            if scope
            else session.material_id
            if session
            else self.runtime.context().browsing
        )
        material = self.runtime.material(material_id)
        material = material.model_copy(deep=True) if material else None
        if not material:
            return
        end = (
            len(material.content)
            if scope
            else session.options.read_through
            if session and session.options and (session.options.read_through is not None)
            else reading_end(material)
        )
        self._source_material, self._source_end = (material.id, end)
        self._document_ready = False
        self._reader_book = None
        self._reader_target = None
        self._reader_error = ""
        self._pending_position = None
        self.search_tasks.invalidate()
        self._results = []

        def received(prepared):
            sections, book = (prepared.sections, prepared.book)
            reader_error = self.runtime.texts["reader_failed"] if prepared.error_code else ""
            self._source_stale = False
            self._document_ready = True
            self._sections = [s.model_dump() for s in sections]
            self._source_full = material.content
            section = next((s for s in sections if s.id == section_id), None)
            if not scope and (not self._preview):
                self._source_section = section.id if section else ""
            self._source_offset = section.start_char if section else 0
            self._source_limit = section.end_char if section else end
            self._reader_book = book
            self._reader_error = reader_error
            self._reader_id = token_hex(16) if book else ""
            self._reader_generation = self.document_tasks.generation
            self._source_text = material.content[
                self._source_offset : min(self._source_limit, self._source_offset + 40000)
            ]
            self.runtime.document()
            self.runtime.changed()
            snapshot = self._preview or self._source_snapshot
            span = snapshot.focus if snapshot else None
            if self._pending_position:
                start, stop = self._pending_position
                self._pending_position = None
                self._show_position(start, stop)
            elif span:
                self._show_position(span.start_char, span.end_char)

        request = SourceLoadRequest(
            material.model_copy(deep=True), end, section_id, self.runtime.asset_directory
        )
        self.runtime.submit("document", BlockingRequest("source", (request,)), received)
        self.runtime.changed()

    def loadMoreSource(self):
        start = self._source_offset + len(self._source_text)
        chunk = self._source_full[start : min(start + 40000, self._source_limit)]
        if chunk:
            self._source_text += chunk
            self.runtime.append(chunk)
            self.runtime.changed()

    def _snapshot(self, base=None, focus=None, kind=None, label=""):
        return TurnSourceSnapshot(
            material_id=self._source_material,
            source_hash=source_hash(self._source_full),
            read_through=self._source_end,
            base=base,
            focus=focus,
            focus_kind=kind,
            section_id=self._source_section or None,
            label=label,
            quote=self._source_full[(focus or base).start_char : (focus or base).end_char]
            if focus or base
            else "",
        )

    def selectSection(self, section_id: str):
        section = next((s for s in self._sections if s["id"] == section_id), None)
        if section and self.runtime.context().route != "scope" and (not self._preview):
            self._source_snapshot = self._snapshot(
                base=SourceSpan(**{k: section[k] for k in ("id", "start_char", "end_char")}),
                label=section["label"],
            )
        self._source_scroll = 0.0
        self._reader_position = section["start_char"] if section else 0
        self.loadSource(section_id)
        self.runtime.changed()

    def selectSource(self, start: int, end: int):
        if self._source_stale or not self._document_ready:
            return
        try:
            a, b = sorted(
                (utf16_to_python(self._source_text, start), utf16_to_python(self._source_text, end))
            )
            a, b = (a + self._source_offset, b + self._source_offset)
            if a == b:
                paragraphs = document_paragraphs(
                    self._source_full, self._source_offset, self._source_limit
                )
                span = next((p for p in paragraphs if p.start_char <= a <= p.end_char), None)
                if not span:
                    return
                a, b = (span.start_char, span.end_char)
            self._select_source_range(a, b, "paragraph" if start == end else "text")
        except ValueError as exc:
            self.runtime.failed(exc)

    def _select_source_range(self, a: int, b: int, kind: str) -> None:
        if self.runtime.context().route == "scope":
            self._scope_pending[self.runtime.context().browsing] = b
        else:
            snapshot = self._preview or self._source_snapshot
            base = snapshot.base if snapshot else None
            if self._preview:
                self._source_section = self._preview.section_id or ""
                self._saved_current = None
                self._view_mode = "current"
                self._preview = None
            if base and (not base.start_char <= a < b <= base.end_char):
                base = None
                self._source_section = ""
            span = SourceSpan(id=f"selection_{a}_{b}", start_char=a, end_char=b)
            self._source_snapshot = self._snapshot(
                base=base, focus=span, kind=kind, label=self._source_full[a:b][:80]
            )
        if kind == "paragraph":
            self._show_position(a, b)
        self.runtime.changed()

    def clearSource(self):
        if self._source_snapshot and self._source_snapshot.focus and self._source_snapshot.base:
            base = self._source_snapshot.base
            label = next(
                (s["label"] for s in self._sections if s["id"] == base.id),
                self.runtime.texts["chapter"],
            )
            self._source_snapshot = self._snapshot(base=base, label=label)
        else:
            self._source_snapshot = None
        self.runtime.changed()

    def snapshot(self) -> TurnSourceSnapshot | None:
        snapshot = (
            self._saved_current.get("_source_snapshot")
            if self._saved_current
            else self._source_snapshot
        )
        return snapshot.model_copy(deep=True) if snapshot else None

    def scheduleSourceSearch(self, query: str) -> None:
        self.search_tasks.invalidate()
        self._pending_search = (self.document_tasks.generation, self._source_material, query)
        self.runtime.debounce()

    def search_after_pause(self) -> None:
        pending = self._pending_search
        self._pending_search = None
        if (
            pending
            and pending[:2] == (self.document_tasks.generation, self._source_material)
            and (self.runtime.context().route in {"scope", "chat"})
            and self._document_ready
            and (not self._source_stale)
        ):
            self.searchSource(pending[2])

    def searchSource(self, query: str):
        request = BlockingRequest("search", (self._source_full, self._source_end, query))
        self.runtime.submit("search", request, self._set_results)

    def _set_results(self, results):
        self._results = results
        self.runtime.changed()

    def _show_position(self, start, end):
        if not self._document_ready:
            self._pending_position = (start, end)
            return
        if not 0 <= start < end <= self._source_end:
            return
        if self._reader_book and (not self._source_offset <= start < end <= self._source_limit):
            self.loadSource("")
            self._pending_position = (start, end)
            return
        if self._reader_book:
            self._reader_target = (start, end)
            self.runtime.reader_selection(self._reader_id, start, end)
            return
        if not self._source_offset <= start < end <= self._source_limit:
            self._source_offset = max(0, start - 500)
            self._source_limit = self._source_end
            self._source_text = self._source_full[
                self._source_offset : min(self._source_limit, max(end, start + 40000))
            ]
            self.runtime.document()
        while end > self._source_offset + len(self._source_text):
            previous_length = len(self._source_text)
            self.loadMoreSource()
            if len(self._source_text) == previous_length:
                return
        self.runtime.selection(
            python_to_utf16(self._source_text, start - self._source_offset),
            python_to_utf16(self._source_text, end - self._source_offset),
        )

    def showSearchResult(self, start: int, end: int):
        self._show_position(start, end)

    def previewMessage(self, message_id: str):
        session = self.runtime.session()
        message = (
            next((m for m in session.messages if m.id == message_id), None) if session else None
        )
        if not message or not message.source_context:
            return
        self.preserve_current()
        self._view_mode = "preview"
        self.document_tasks.invalidate()
        self.search_tasks.invalidate()
        self._results = []
        self._pending_position = None
        self._preview = message.source_context.model_copy(deep=True)
        material = self.runtime.material(self._preview.material_id)
        self._source_open = True
        if (
            not material
            or source_hash(material.content) != self._preview.source_hash
            or self._preview.index_version != "source-view-v1"
        ):
            self._source_stale = True
            self._reader_book = None
            self._reader_id = ""
            self._document_ready = False
            self._source_text = self._preview.quote
            self._source_full = self._preview.quote
            self._source_offset = 0
            self._source_limit = self._source_end = len(self._source_text)
            self._sections = []
            self.runtime.document()
            self.runtime.failed(self.runtime.texts["stale"])
        else:
            self.loadSource(self._preview.section_id or "")
        self.runtime.changed()

    def closePreview(self):
        self.restore_current()
        self.loadSource(self._source_section)
        self.runtime.changed()
