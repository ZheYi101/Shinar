import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "design"
import "components"
import "pages"

Item {
    id: root
    property int currentPage: learningViewModel.hasSession ? 1 : 0
    readonly property bool compact: width < AppTheme.compactBreakpoint
    readonly property bool showContext: width >= AppTheme.expandedBreakpoint && currentPage === 1
    readonly property int pageMargin: compact ? AppTheme.compactPageMargin : AppTheme.pageMargin
    readonly property var destinations: [
        {label: "材料", symbol: "library_books"}, {label: "对话", symbol: "chat_bubble"}
    ]
    Rectangle { anchors.fill: parent; color: AppTheme.surface }
    ColumnLayout {
        anchors.fill: parent
        spacing: 0
        WindowTitleBar {
            Layout.fillWidth: true
            Layout.preferredHeight: 56
            onNavigate: page => root.currentPage = page
        }
        MProgress { visible: learningViewModel.busy; Layout.fillWidth: true; Layout.preferredHeight: 4 }
        MCard {
            visible: learningViewModel.errorMessage.length > 0
            Layout.leftMargin: root.pageMargin; Layout.rightMargin: root.pageMargin
            color: AppTheme.errorContainer
            MLabel { text: learningViewModel.errorMessage; color: AppTheme.colorOnErrorContainer; Accessible.role: Accessible.AlertMessage }
            RowLayout {
                MButton { text: "重试"; variant: "text"; enabled: learningViewModel.canRetryOperation && !learningViewModel.busy; onClicked: learningViewModel.retryOperation() }
                MButton { text: "关闭提示"; variant: "text"; onClicked: learningViewModel.dismissError() }
            }
        }
        RowLayout {
            Layout.fillWidth: true; Layout.fillHeight: true
            spacing: 0
            Rectangle {
                visible: !root.compact
                Layout.preferredWidth: AppTheme.railWidth; Layout.fillHeight: true
                color: AppTheme.surfaceContainerLow
                ColumnLayout {
                    anchors.fill: parent; anchors.topMargin: 16
                    spacing: AppTheme.gapSmall
                    Repeater {
                        model: root.destinations
                        MNavItem {
                            required property var modelData
                            required property int index
                            objectName: "nav" + index
                            text: modelData.label
                            symbol: modelData.symbol
                            checked: root.currentPage === index
                            onClicked: root.currentPage = index
                        }
                    }
                    Item { Layout.fillHeight: true }
                    MIconButton { objectName: "nav2"; Layout.alignment: Qt.AlignHCenter; symbol: "history"; label: "复盘" + (learningViewModel.dueReviewCount > 0 ? " · " + learningViewModel.dueReviewCount : ""); onClicked: root.currentPage = 2 }
                    MIconButton { objectName: "nav3"; Layout.alignment: Qt.AlignHCenter; Layout.bottomMargin: 16; symbol: "settings"; label: "设置"; onClicked: root.currentPage = 3 }
                }
            }
            StackLayout {
                currentIndex: root.currentPage
                Layout.fillWidth: true; Layout.fillHeight: true
                Layout.margins: root.pageMargin
                MaterialsPage { onNavigate: page => root.currentPage = page }
                ConversationPage { onOpenContext: contextDialog.open(); onOpenMaterials: root.currentPage = 0 }
                ReviewPage {}
                SettingsPage {}
            }
            MCard {
                visible: root.showContext
                Layout.preferredWidth: AppTheme.contextWidth; Layout.fillWidth: false
                Layout.fillHeight: true; Layout.topMargin: 24; Layout.bottomMargin: 24; Layout.rightMargin: 24
                MLabel { text: "本次语境"; role: "title" }
                MLabel { text: learningViewModel.materialTitle; role: "label" }
                ScrollView {
                    id: contextScroll
                    Layout.fillWidth: true; Layout.fillHeight: true
                    contentWidth: availableWidth
                    contentHeight: contextSummaryText.implicitHeight
                    MLabel { id: contextSummaryText; width: contextScroll.availableWidth; height: implicitHeight; text: learningViewModel.materialSummary; role: "supporting" }
                }
            }
        }
        Rectangle {
            visible: root.compact
            Layout.fillWidth: true; Layout.preferredHeight: AppTheme.navigationBarHeight
            color: AppTheme.surfaceContainer
            RowLayout {
                anchors.fill: parent; spacing: 0
                Repeater {
                    model: root.destinations
                    MNavItem {
                        required property var modelData
                        required property int index
                        objectName: "bottomNav" + index
                        Layout.fillWidth: true
                        text: modelData.label
                        symbol: modelData.symbol
                        checked: root.currentPage === index
                        onClicked: root.currentPage = index
                    }
                }
            }
        }
    }
    MDialog {
        id: contextDialog
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(root.width - 32, 560)
        height: Math.min(root.height - 32, 620)
        title: "本次语境"
        standardButtons: Dialog.Close
        contentItem: ScrollView {
            contentWidth: availableWidth
            MLabel { width: parent.width; text: learningViewModel.materialSummary }
        }
    }
    MSnackbar {
        id: snackbar
        parent: Overlay.overlay
        x: Math.max(16, (root.width - width) / 2)
        y: root.height - height - (root.compact ? 96 : 24)
        width: Math.min(root.width - 32, 420)
    }
    Connections {
        target: learningViewModel
        function onReviewReady() { root.currentPage = 2 }
        function onPracticeStarted() { root.currentPage = 1 }
        function onStatusChanged() {
            if (!learningViewModel.busy && learningViewModel.errorMessage.length === 0 && learningViewModel.status !== "练习已更新。") {
                snackbar.message = learningViewModel.status
                snackbar.open()
            }
        }
    }
    Shortcut { sequence: "Ctrl+1"; context: Qt.ApplicationShortcut; onActivated: root.currentPage = 0 }
    Shortcut { sequence: "Ctrl+2"; context: Qt.ApplicationShortcut; onActivated: root.currentPage = 1 }
    Shortcut { sequence: "Ctrl+,"; context: Qt.ApplicationShortcut; onActivated: root.currentPage = 3 }
}
