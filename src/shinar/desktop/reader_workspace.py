"""Transient source, preview and reader state on the workspace facade."""

from __future__ import annotations

import base64
from secrets import token_hex
from typing import Any

from PySide6.QtCore import QCoreApplication, Property, Signal, Slot

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


class ReaderWorkspace:
    changed = Signal()

    modelsChanged = Signal()

    documentChanged = Signal()

    sourceAppend = Signal(str)

    selectionRequested = Signal(int, int)

    readerSelectionRequested = Signal(str, int, int)

    editorRestoreRequested = Signal(int, float)

    focusComposerRequested = Signal()

    @Property(bool, notify=changed)
    def sourceOpen(self):
        return self._source_open

    @Slot()
    def toggleSource(self):
        if self._source_open:
            self._request["document"] += 1
            self._request["search"] += 1
        self._preview = None
        self._source_open = not self._source_open
        if self._source_open:
            self.loadSource(self._source_section)
        else:
            self.focusComposerRequested.emit()
        self.changed.emit()

    @Property(str, notify=documentChanged)
    def sourceText(self):
        return self._source_text

    @Property(bool, notify=changed)
    def readerAvailable(self) -> bool:
        return self._reader_book is not None and not self._reader_error and self._document_ready

    @Property(str, notify=documentChanged)
    def readerId(self) -> str:
        return self._reader_id

    @Property(str, notify=changed)
    def readerError(self) -> str:
        return self._reader_error

    def reader_active(self, identity: str) -> bool:
        return bool(
            identity and identity == self._reader_id and self.readerAvailable
            and not self._source_stale
            and self._reader_generation == self._request["document"]
            and (self._route == "scope" or self._route == "chat" and self._source_open)
        )

    def reader_document(self, identity: str) -> dict[str, Any]:
        if not self.reader_active(identity):
            return {}
        first = self._sections[0]["start_char"] if self._sections else 0
        position = max(self._source_offset, min(self._reader_position or first, self._source_limit))
        return dict(
            identity=identity,
            epub=base64.b64encode(self._reader_book.data).decode("ascii"),
            chapters=self._reader_book.chapters,
            language=self.sourceLanguage,
            start=self._source_offset,
            end=self._source_limit,
            position=position,
            target=self._reader_target,
            boundary=self.pendingEnd if self._route == "scope" else -1,
        )

    @Slot(str, int, int, str)
    def selectReaderRange(self, identity: str, start: int, end: int, kind: str) -> None:
        if (
            self.reader_active(identity) and kind in {"paragraph", "text"}
            and self._source_offset <= start < end <= self._source_limit
        ):
            self._select_source_range(start, end, kind)

    @Slot(str, int)
    def saveReaderPosition(self, identity: str, position: int) -> None:
        if self.reader_active(identity) and not self._preview and self._route == "chat":
            if self._source_offset <= position <= self._source_limit:
                self._reader_position = position

    @Slot(str)
    def readerFailed(self, identity: str) -> None:
        if identity == self._reader_id:
            self._reader_error = QCoreApplication.translate("Desktop", "书籍排版暂不可用，已显示文本。")
            self.changed.emit()

    @Property(list, notify=documentChanged)
    def sections(self):
        return self._sections

    @Property(list, notify=changed)
    def searchResults(self):
        return self._results

    @Property(bool, notify=changed)
    def historicalSource(self):
        return self._preview is not None

    @Property(bool, notify=changed)
    def sourceStale(self):
        return self._source_stale

    @Property(bool, notify=changed)
    def documentReady(self):
        return self._document_ready

    @Property(str, notify=documentChanged)
    def sourceLanguage(self):
        material = self.workbench.get_material(self._source_material)
        return material.source_language.value if material else ""

    @Property(float, notify=documentChanged)
    def sourceScroll(self):
        return self._source_scroll

    @Slot(float)
    def saveSourceScroll(self, value: float):
        if self._route == "chat" and not self._preview:
            self._source_scroll = value

    @Property(str, notify=changed)
    def sourceLabel(self):
        snapshot = self._preview or self._source_snapshot
        return snapshot.label if snapshot else ""

    @Property(bool, notify=changed)
    def hasSource(self):
        return self._source_snapshot is not None

    @Property(bool, notify=changed)
    def sourceHasMore(self):
        return self._source_offset + len(self._source_text) < self._source_limit

    @Slot(str)
    def loadSource(self, section_id: str):
        scope = self._route == "scope"
        session = self.workbench.session
        material_id = (
            self._browsing if scope else session.material_id if session else self._browsing
        )
        material = self.workbench.get_material(material_id)
        if not material:
            return
        end = (
            len(material.content)
            if scope
            else session.options.read_through
            if session and session.options and session.options.read_through is not None
            else reading_end(material)
        )
        self._source_material, self._source_end = material.id, end
        self._document_ready = False
        self._reader_book = None
        self._reader_target = None
        self._reader_error = ""
        self._pending_position = None
        self._request["search"] += 1
        self._results = []

        def received(prepared):
            sections, book = prepared.sections, prepared.book
            reader_error = (QCoreApplication.translate("Desktop", "书籍排版暂不可用，已显示文本。")
                            if prepared.error_code else "")
            self._source_stale = False
            self._document_ready = True
            self._sections = [s.model_dump() for s in sections]
            self._source_full = material.content
            section = next((s for s in sections if s.id == section_id), None)
            if not scope and not self._preview:
                self._source_section = section.id if section else ""
            self._source_offset = section.start_char if section else 0
            self._source_limit = section.end_char if section else end
            self._reader_book = book
            self._reader_error = reader_error
            self._reader_id = token_hex(16) if book else ""
            self._reader_generation = self._request["document"]
            self._source_text = material.content[
                self._source_offset : min(self._source_limit, self._source_offset + 40000)
            ]
            self.documentChanged.emit()
            self.changed.emit()
            snapshot = self._preview or self._source_snapshot
            span = snapshot.focus if snapshot else None
            if self._pending_position:
                start, stop = self._pending_position
                self._pending_position = None
                self._show_position(start, stop)
            elif span:
                self._show_position(span.start_char, span.end_char)

        request = SourceLoadRequest(
            material.model_copy(deep=True), end, section_id, self.workbench.source_asset_directory
        )
        self._request_job("document", BlockingRequest("source", (request,)), received)
        self.changed.emit()

    @Slot()
    def loadMoreSource(self):
        start = self._source_offset + len(self._source_text)
        chunk = self._source_full[start : min(start + 40000, self._source_limit)]
        if chunk:
            self._source_text += chunk
            self.sourceAppend.emit(chunk)
            self.changed.emit()

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

    @Slot(str)
    def selectSection(self, section_id: str):
        section = next((s for s in self._sections if s["id"] == section_id), None)
        if section and self._route != "scope" and not self._preview:
            self._source_snapshot = self._snapshot(
                base=SourceSpan(**{k: section[k] for k in ("id", "start_char", "end_char")}),
                label=section["label"],
            )
        self._source_scroll = 0.0
        self._reader_position = section["start_char"] if section else 0
        self.loadSource(section_id)
        self.changed.emit()

    @Slot(int, int)
    def selectSource(self, start: int, end: int):
        if self._source_stale or not self._document_ready:
            return
        try:
            a, b = sorted(
                (utf16_to_python(self._source_text, start), utf16_to_python(self._source_text, end))
            )
            a, b = a + self._source_offset, b + self._source_offset
            if a == b:
                paragraphs = document_paragraphs(
                    self._source_full, self._source_offset, self._source_limit
                )
                span = next((p for p in paragraphs if p.start_char <= a <= p.end_char), None)
                if not span:
                    return
                a, b = span.start_char, span.end_char
            self._select_source_range(a, b, "paragraph" if start == end else "text")
        except ValueError as exc:
            self._fail(exc)

    def _select_source_range(self, a: int, b: int, kind: str) -> None:
        if self._route == "scope":
            self._scope_pending[self._browsing] = b
        else:
            snapshot = self._preview or self._source_snapshot
            base = snapshot.base if snapshot else None
            if self._preview:
                self._source_section = self._preview.section_id or ""
                self._preview = None
            if base and not base.start_char <= a < b <= base.end_char:
                base = None
                self._source_section = ""
            span = SourceSpan(id=f"selection_{a}_{b}", start_char=a, end_char=b)
            self._source_snapshot = self._snapshot(
                base=base, focus=span, kind=kind, label=self._source_full[a:b][:80],
            )
        if kind == "paragraph":
            self._show_position(a, b)
        self.changed.emit()

    @Slot()
    def clearSource(self):
        if self._source_snapshot and self._source_snapshot.focus and self._source_snapshot.base:
            base = self._source_snapshot.base
            label = next(
                (s["label"] for s in self._sections if s["id"] == base.id),
                QCoreApplication.translate("Desktop", "本章"),
            )
            self._source_snapshot = self._snapshot(base=base, label=label)
        else:
            self._source_snapshot = None
        self.changed.emit()

    def snapshot(self) -> TurnSourceSnapshot | None:
        return self._source_snapshot.model_copy(deep=True) if self._source_snapshot else None

    @Slot(str)
    def scheduleSourceSearch(self, query: str) -> None:
        self._request["search"] += 1
        self._pending_search = (self._request["document"], self._source_material, query)
        self._search_timer.start()

    def _search_after_pause(self) -> None:
        pending = self._pending_search
        self._pending_search = None
        if (pending and pending[:2] == (self._request["document"], self._source_material)
                and self._route in {"scope", "chat"} and self._document_ready and not self._source_stale):
            self.searchSource(pending[2])

    @Slot(str)
    def searchSource(self, query: str):
        request = BlockingRequest("search", (self._source_full, self._source_end, query))
        self._request_job("search", request, self._set_results)

    def _set_results(self, results):
        self._results = results
        self.changed.emit()

    def _show_position(self, start, end):
        if not self._document_ready:
            self._pending_position = (start, end)
            return
        if not 0 <= start < end <= self._source_end:
            return
        if self._reader_book and not self._source_offset <= start < end <= self._source_limit:
            self.loadSource("")
            self._pending_position = (start, end)
            return
        if self._reader_book:
            self._reader_target = (start, end)
            self.readerSelectionRequested.emit(self._reader_id, start, end)
            return
        if not self._source_offset <= start < end <= self._source_limit:
            self._source_offset = max(0, start - 500)
            self._source_limit = self._source_end
            self._source_text = self._source_full[
                self._source_offset : min(self._source_limit, max(end, start + 40000))
            ]
            self.documentChanged.emit()
        while end > self._source_offset + len(self._source_text):
            previous_length = len(self._source_text)
            self.loadMoreSource()
            if len(self._source_text) == previous_length:
                return
        self.selectionRequested.emit(
            python_to_utf16(self._source_text, start - self._source_offset),
            python_to_utf16(self._source_text, end - self._source_offset),
        )

    @Slot(int, int)
    def showSearchResult(self, start: int, end: int):
        self._show_position(start, end)

    @Slot(str)
    def previewMessage(self, message_id: str):
        session = self.workbench.session
        message = (
            next((m for m in session.messages if m.id == message_id), None) if session else None
        )
        if not message or not message.source_context:
            return
        self._request["document"] += 1
        self._request["search"] += 1
        self._results = []
        self._pending_position = None
        self._preview = message.source_context.model_copy(deep=True)
        material = self.workbench.get_material(self._preview.material_id)
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
            self.documentChanged.emit()
            self._fail(
                QCoreApplication.translate("Desktop", "原文版本已改变，显示发送时保存的引文。")
            )
        else:
            self.loadSource(self._preview.section_id or "")
        self.changed.emit()

    @Slot()
    def closePreview(self):
        self._preview = None
        self.loadSource(self._source_section)
        self.changed.emit()



