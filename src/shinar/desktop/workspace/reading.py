"""Qt properties and slots delegate to the non-Qt reading owner."""

from PySide6.QtCore import Property, Signal, Slot
from shinar.desktop.presentation.conversation_presentation import display_value


class ReaderPropertiesMixin:
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
        return display_value(self._reading.sourceOpen)

    @Slot()
    def toggleSource(self):
        return self._reading.toggleSource()

    @Property(str, notify=documentChanged)
    def sourceText(self):
        return display_value(self._reading.sourceText)

    @Property(bool, notify=changed)
    def readerAvailable(self):
        return display_value(self._reading.readerAvailable)

    @Property(str, notify=documentChanged)
    def readerId(self):
        return display_value(self._reading.readerId)

    @Property(str, notify=changed)
    def readerError(self):
        return display_value(self._reading.readerError)

    def reader_active(self, identity: str):
        return self._reading.reader_active(identity)

    def reader_document(self, identity: str):
        return self._reading.reader_document(identity)

    @Slot(str, int, int, str)
    def selectReaderRange(self, identity: str, start: int, end: int, kind: str):
        return self._reading.selectReaderRange(identity, start, end, kind)

    @Slot(str, int)
    def saveReaderPosition(self, identity: str, position: int):
        return self._reading.saveReaderPosition(identity, position)

    @Slot(str)
    def readerFailed(self, identity: str):
        return self._reading.readerFailed(identity)

    @Property(list, notify=documentChanged)
    def sections(self):
        return display_value(self._reading.sections)

    @Property(list, notify=changed)
    def searchResults(self):
        return display_value(self._reading.searchResults)

    @Property(bool, notify=changed)
    def historicalSource(self):
        return display_value(self._reading.historicalSource)

    @Property(bool, notify=changed)
    def sourceStale(self):
        return display_value(self._reading.sourceStale)

    @Property(bool, notify=changed)
    def documentReady(self):
        return display_value(self._reading.documentReady)

    @Property(str, notify=documentChanged)
    def sourceLanguage(self):
        return display_value(self._reading.sourceLanguage)

    @Property(float, notify=documentChanged)
    def sourceScroll(self):
        return display_value(self._reading.sourceScroll)

    @Slot(float)
    def saveSourceScroll(self, value: float):
        return self._reading.saveSourceScroll(value)

    @Property(str, notify=changed)
    def sourceLabel(self):
        return display_value(self._reading.sourceLabel)

    @Property(bool, notify=changed)
    def hasSource(self):
        return display_value(self._reading.hasSource)

    @Property(bool, notify=changed)
    def sourceHasMore(self):
        return display_value(self._reading.sourceHasMore)

    @Slot(str)
    def loadSource(self, section_id: str):
        return self._reading.loadSource(section_id)

    @Slot()
    def loadMoreSource(self):
        return self._reading.loadMoreSource()

    @Slot(str)
    def selectSection(self, section_id: str):
        return self._reading.selectSection(section_id)

    @Slot(int, int)
    def selectSource(self, start: int, end: int):
        return self._reading.selectSource(start, end)

    @Slot()
    def clearSource(self):
        return self._reading.clearSource()

    def snapshot(self):
        return self._reading.snapshot()

    @Slot(str)
    def scheduleSourceSearch(self, query: str):
        return self._reading.scheduleSourceSearch(query)

    def _search_after_pause(self):
        return self._reading.search_after_pause()

    @Slot(str)
    def searchSource(self, query: str):
        return self._reading.searchSource(query)

    @Slot(int, int)
    def showSearchResult(self, start: int, end: int):
        return self._reading.showSearchResult(start, end)

    @Slot(str)
    def previewMessage(self, message_id: str):
        return self._reading.previewMessage(message_id)

    @Slot()
    def closePreview(self):
        return self._reading.closePreview()
