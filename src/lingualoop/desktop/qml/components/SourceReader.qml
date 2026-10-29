import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../design"

Item {
    id: reader
    property bool scopeMode: false
    property bool programmatic: false
    signal back()
    ColumnLayout {
        anchors.fill: parent; spacing: 0
        RowLayout {
            Layout.fillWidth: true; Layout.preferredHeight: 36; spacing: 0
            MIconButton { symbol: "arrow_back"; label: reader.scopeMode ? "返回材料" : "返回对话"; onClicked: reader.back() }
            MIconButton { symbol: "menu"; label: "目录"; enabled: !workspace.sourceStale; onClicked: contents.open() }
            Item { Layout.fillWidth: true }
            MButton { visible: workspace.historicalSource; text: "返回当前指向"; variant: "text"; onClicked: workspace.closePreview() }
            MIconButton { symbol: "search"; label: "查找原文"; enabled: !workspace.sourceStale; onClicked: { findPopup.open(); searchInput.forceActiveFocus() } }
        }
        ScrollView {
            id: sourceScroll
            objectName: "sourceScroll"
            Layout.fillWidth: true; Layout.fillHeight: true
            clip: true; contentWidth: availableWidth
            Column {
                width: sourceScroll.availableWidth; spacing: 8
                TextEdit {
                    id: document
                    objectName: "sourceDocument"
                    width: parent.width
                    leftPadding: 20; rightPadding: 20; topPadding: 12; bottomPadding: 24
                    readOnly: true; selectByMouse: true; selectByKeyboard: true; persistentSelection: true
                    enabled: workspace.documentReady || workspace.sourceStale
                    textFormat: TextEdit.PlainText; wrapMode: TextEdit.Wrap
                    font.family: workspace.sourceLanguage === "japanese" ? AppTheme.japaneseReadingFont : AppTheme.readingFont
                    font.pixelSize: 17
                    color: AppTheme.colorOnSurface
                    selectionColor: Qt.alpha(AppTheme.primary, 0.22); selectedTextColor: AppTheme.colorOnSurface
                    Accessible.name: "原文"
                    PointHandler {
                        acceptedButtons: Qt.LeftButton
                        onActiveChanged: if (!active && !reader.programmatic) workspace.selectSource(document.selectionStart, document.selectionEnd)
                    }
                    Keys.onReleased: function(event) {
                        if (!reader.programmatic && (event.key === Qt.Key_Shift || (event.modifiers & Qt.ShiftModifier))) workspace.selectSource(selectionStart, selectionEnd)
                    }
                }
                MButton { visible: workspace.sourceHasMore; text: "继续加载"; variant: "text"; anchors.horizontalCenter: parent.horizontalCenter; onClicked: workspace.loadMoreSource() }
            }
        }
    }
    Popup {
        id: contents
        y: 36; width: Math.min(reader.width - 8, 360); height: Math.min(reader.height - 44, 420)
        background: Rectangle { color: AppTheme.surface; border.color: AppTheme.outlineVariant; radius: 5 }
        contentItem: ScrollView {
            contentWidth: availableWidth
            ColumnLayout {
                width: parent.width
                MLabel { visible: workspace.sections.length === 0; text: "无章节目录"; role: "supporting" }
                Repeater { model: workspace.sections
                    MButton { required property var modelData; Layout.fillWidth: true; text: modelData.label; variant: "text"; onClicked: { workspace.selectSection(modelData.id); contents.close() } contentItem: Text { text: parent.text; font: parent.font; color: AppTheme.colorOnSurface; wrapMode: Text.Wrap } }
                }
            }
        }
    }
    Popup {
        id: findPopup
        x: Math.max(0, reader.width - width); y: 36
        width: Math.min(reader.width - 8, 400); height: Math.min(reader.height - 44, 400)
        background: Rectangle { color: AppTheme.surface; border.color: AppTheme.outlineVariant; radius: 5 }
        contentItem: ColumnLayout {
            RowLayout {
                MTextField { id: searchInput; Layout.fillWidth: true; placeholderText: "查找原文"; onTextEdited: searchTimer.restart() }
                MIconButton { symbol: "close"; label: "关闭查找"; onClicked: findPopup.close() }
            }
            ScrollView {
                Layout.fillWidth: true; Layout.fillHeight: true; contentWidth: availableWidth
                ColumnLayout { width: parent.width
                    MLabel { visible: searchInput.text.length > 0 && workspace.searchResults.length === 0; text: "未找到"; role: "supporting" }
                    Repeater { model: workspace.searchResults
                        MButton { required property var modelData; Layout.fillWidth: true; text: modelData.text; variant: "text"; implicitHeight: Math.max(40, contentItem.implicitHeight+16); contentItem: Text { text: parent.text; font: parent.font; color: AppTheme.colorOnSurface; wrapMode: Text.Wrap } onClicked: { workspace.showSearchResult(modelData.start, modelData.end); findPopup.close() } }
                    }
                }
            }
        }
    }
    Timer { id: searchTimer; interval: 200; onTriggered: workspace.searchSource(searchInput.text) }
    Shortcut { sequence: "Ctrl+F"; enabled: reader.visible; onActivated: { findPopup.open(); searchInput.forceActiveFocus() } }
    Shortcut { sequence: "Escape"; enabled: reader.visible && !contents.visible && !findPopup.visible; onActivated: { if (workspace.historicalSource) workspace.closePreview(); else if (!reader.scopeMode && workspace.hasSource) workspace.clearSource(); else reader.back() } }
    Connections {
        target: workspace
        function onDocumentChanged() { reader.programmatic = true; document.text = workspace.sourceText; Qt.callLater(function() { sourceScroll.contentItem.contentY = workspace.sourceScroll; reader.programmatic = false }) }
        function onSourceAppend(chunk) { reader.programmatic = true; document.insert(document.length, chunk); Qt.callLater(function() { reader.programmatic = false }) }
        function onSelectionRequested(start, end) {
            reader.programmatic = true; document.select(start, end)
            const rect = document.positionToRectangle(start)
            sourceScroll.contentItem.contentY = Math.max(0, Math.min(rect.y-80, document.height-sourceScroll.height))
            Qt.callLater(function() { reader.programmatic = false })
        }
    }
    Connections { target: sourceScroll.contentItem; function onContentYChanged() { if (reader.visible && !reader.programmatic) workspace.saveSourceScroll(sourceScroll.contentItem.contentY) } }
    Component.onCompleted: document.text = workspace.sourceText
}
