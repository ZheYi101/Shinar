import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../design"

Rectangle {
    id: bar
    signal navigate(int page)
    signal toggleSidebar()
    property bool compactNavigation: false
    implicitHeight: AppTheme.topBarHeight
    color: AppTheme.surface
    MouseArea {
        anchors.fill: parent
        objectName: "windowDragArea"
        acceptedButtons: Qt.LeftButton
        onPressed: desktopWindow.startMove()
        onDoubleClicked: desktopWindow.toggleMaximized()
    }
    RowLayout {
        anchors.fill: parent; anchors.leftMargin: 0; anchors.rightMargin: 4
        spacing: 0
        MIconButton { objectName: "sidebarToggle"; symbol: bar.compactNavigation || workspace.collapsed ? "panel_open" : "panel_left"; label: bar.compactNavigation ? qsTr("打开导航") : workspace.collapsed ? qsTr("展开侧栏") : qsTr("收起侧栏"); implicitHeight: AppTheme.topBarHeight; onClicked: bar.toggleSidebar() }
        Item { Layout.fillWidth: true }
        MLabel { objectName: "mockDialogueNotice"; visible: learningViewModel.providerLabel.indexOf("Mock") >= 0; text: bar.width < 600 ? "Mock" : qsTr("Mock 对话"); role: "supporting"; font.pixelSize: 11; Layout.fillWidth: false; Layout.rightMargin: 12; ToolTip.visible: mockHover.hovered; ToolTip.text: qsTr("离线测试语料，未调用对话模型。"); ToolTip.delay: 650; HoverHandler { id: mockHover } }
        MButton { objectName: "openSourceButton"; visible: workspace.route === "chat"; text: qsTr("原文"); variant: "text"; implicitHeight: AppTheme.topBarHeight; enabled: learningViewModel.hasSession; onClicked: workspace.toggleSource() }
        WindowAction { visible: workspace.route === "chat"; glyph: "more"; label: qsTr("对话操作"); objectName: "conversationMenuButton"; onClicked: secondaryMenu.open() }
        WindowAction { label: qsTr("最小化"); objectName: "windowMinimizeButton"; onClicked: desktopWindow.minimize() }
        WindowAction { glyph: desktopWindow.maximized ? "restore" : "maximize"; label: desktopWindow.maximized ? qsTr("还原窗口") : qsTr("最大化"); objectName: "windowMaximizeButton"; onClicked: desktopWindow.toggleMaximized() }
        WindowAction { glyph: "close"; label: qsTr("关闭窗口"); objectName: "windowCloseButton"; onClicked: desktopWindow.close() }
    }
    Menu {
        id: secondaryMenu
        x: Math.max(8, bar.width - width - 148); y: bar.height
        MenuItem { objectName: "finishDiscussionButton"; visible: workspace.route === "chat"; text: qsTr("结束并复盘"); enabled: learningViewModel.sessionActive && !workspace.threadLocked; onTriggered: learningViewModel.finishPractice() }
        MenuItem { objectName: "openHistoryButton"; visible: workspace.route === "chat"; text: qsTr("本材料的对话"); onTriggered: workspace.browseMaterial(learningViewModel.selectedMaterialId) }
        MenuItem { visible: workspace.route === "chat"; text: qsTr("本轮信息"); onTriggered: turnInfo.open() }
        MenuItem { text: qsTr("复盘") + (learningViewModel.dueReviewCount > 0 ? " · " + learningViewModel.dueReviewCount : ""); onTriggered: bar.navigate(2) }
        MenuItem { text: qsTr("表达复习"); onTriggered: workspace.navigate("queue") }
        MenuItem { text: qsTr("设置"); onTriggered: bar.navigate(3) }
        MenuSeparator {}
        MenuItem { text: qsTr("还原窗口"); enabled: desktopWindow.maximized; onTriggered: desktopWindow.restore() }
        MenuItem { objectName: "exitApplicationMenuItem"; text: qsTr("退出 Shinar"); onTriggered: desktopLifecycle.quit() }
    }
    Popup {
        id: turnInfo
        x: Math.max(8, bar.width-width-16); y: bar.height
        width: Math.min(380, bar.width-24)
        background: Rectangle { color: AppTheme.surface; border.color: AppTheme.outlineVariant; radius: 5 }
        contentItem: ColumnLayout {
            MLabel { text: learningViewModel.responseTiming; role: "supporting" }
            MLabel { text: learningViewModel.preparationStatus; role: "supporting" }
            MLabel { text: learningViewModel.speechStatus; role: "supporting" }
        }
    }
    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: AppTheme.outlineVariant; opacity: 0.55 }
}

