import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../design"

Rectangle {
    id: bar
    signal navigate(int page)
    signal toggleSidebar()
    implicitHeight: 30
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
        MIconButton { objectName: "sidebarToggle"; symbol: "menu"; label: "侧栏"; implicitHeight: 30; onClicked: bar.toggleSidebar() }
        Item { Layout.fillWidth: true }
        MLabel { visible: bar.width > 850 && learningViewModel.providerLabel.indexOf("Mock") >= 0; text: "离线预览"; role: "supporting"; Layout.fillWidth: false; Layout.rightMargin: 12 }
        WindowAction { glyph: "more"; label: "更多：复盘和设置"; objectName: "secondaryMenuButton"; onClicked: secondaryMenu.open() }
        WindowAction { label: "最小化"; objectName: "windowMinimizeButton"; onClicked: desktopWindow.minimize() }
        WindowAction { glyph: desktopWindow.maximized ? "restore" : "maximize"; label: desktopWindow.maximized ? "还原窗口" : "最大化"; objectName: "windowMaximizeButton"; onClicked: desktopWindow.toggleMaximized() }
        WindowAction { glyph: "close"; label: "关闭窗口"; objectName: "windowCloseButton"; onClicked: desktopWindow.close() }
    }
    Menu {
        id: secondaryMenu
        x: Math.max(8, bar.width - width - 148); y: bar.height
        MenuItem { text: "复盘" + (learningViewModel.dueReviewCount > 0 ? " · " + learningViewModel.dueReviewCount : ""); onTriggered: bar.navigate(2) }
        MenuItem { text: "设置"; onTriggered: bar.navigate(3) }
        MenuSeparator {}
        MenuItem { text: "还原窗口"; enabled: desktopWindow.maximized; onTriggered: desktopWindow.restore() }
    }
}

