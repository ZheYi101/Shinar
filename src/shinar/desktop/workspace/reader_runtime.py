"""Private, offline WebEngine profile and a narrow source-selection WebChannel."""

from __future__ import annotations

from importlib.resources import files
import json
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot
from PySide6.QtWebEngineCore import QWebEngineUrlRequestInterceptor, QWebEngineUrlRequestInfo
from PySide6.QtWebEngineQuick import QQuickWebEngineProfile

if TYPE_CHECKING:
    from shinar.desktop.workspace.controller import DesktopWorkspaceController


class ReaderRequests(QWebEngineUrlRequestInterceptor):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        root = Path(str(files("shinar.desktop")))
        self.allowed_files = {
            path.resolve()
            for directory in (root / "reader", root / "qml/assets/fonts")
            for path in directory.rglob("*")
            if path.is_file()
        }

    def allows(self, url: QUrl) -> bool:
        if url.scheme() in {"blob", "data", "about"}:
            return True
        if url.scheme() == "qrc":
            return url.path() == "/qtwebchannel/qwebchannel.js"
        return url.isLocalFile() and Path(url.toLocalFile()).resolve() in self.allowed_files

    def interceptRequest(self, info: QWebEngineUrlRequestInfo) -> None:
        if not self.allows(info.requestUrl()):
            info.block(True)


class ReaderBridge(QObject):
    loaded = Signal(str)
    searchRequested = Signal(str)

    def __init__(
        self, workspace: DesktopWorkspaceController, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self.workspace = workspace

    @Slot(str, result=str)
    def document(self, identity: str) -> str:
        document = self.workspace.reader_document(identity)
        if document:
            document["boundaryLabel"] = self.tr("已读至此")
        return json.dumps(document, ensure_ascii=False)

    @Slot(str, int, int, str)
    def select(self, identity: str, start: int, end: int, kind: str) -> None:
        self.workspace.selectReaderRange(identity, start, end, kind)

    @Slot(str, int)
    def location(self, identity: str, position: int) -> None:
        self.workspace.saveReaderPosition(identity, position)

    @Slot(str)
    def ready(self, identity: str) -> None:
        if self.workspace.reader_active(identity):
            self.loaded.emit(identity)

    @Slot(str)
    def failed(self, identity: str) -> None:
        self.workspace.readerFailed(identity)

    @Slot(str)
    def find(self, identity: str) -> None:
        if self.workspace.reader_active(identity):
            self.searchRequested.emit(identity)


class ReaderRuntime(QObject):
    def __init__(
        self, workspace: DesktopWorkspaceController, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._profile = QQuickWebEngineProfile(self)
        self._profile.setOffTheRecord(True)
        self.requests = ReaderRequests(self)
        self._profile.setUrlRequestInterceptor(self.requests)
        self._profile.downloadRequested.connect(lambda download: download.cancel())
        self._bridge = ReaderBridge(workspace, self)
        self._url = QUrl.fromLocalFile(
            str(files("shinar.desktop").joinpath("reader/index.html"))
        )

    @Property(QObject, constant=True)
    def profile(self) -> QQuickWebEngineProfile:
        return self._profile

    @Property(QObject, constant=True)
    def bridge(self) -> ReaderBridge:
        return self._bridge

    @Property(QUrl, constant=True)
    def url(self) -> QUrl:
        return self._url
