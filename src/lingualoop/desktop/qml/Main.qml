import QtQuick
import QtQuick.Controls.Material
import "design"
import "components"
import org.kde.kirigami as Kirigami

Kirigami.ApplicationWindow {
    id: root
    readonly property var workspaceController: workspace
    flags: Qt.Window | Qt.FramelessWindowHint | Qt.WindowMinMaxButtonsHint
    Material.theme: AppTheme.dark ? Material.Dark : Material.Light
    Material.accent: AppTheme.primary
    visible: initialWindowVisible
    width: 1180
    height: 780
    minimumWidth: 360
    minimumHeight: 560
    title: "LinguaLoop"

    pageStack.initialPage: Kirigami.Page {
        title: "LinguaLoop"
        padding: 0

        WorkbenchScaffold {
            anchors.fill: parent
        }
    }
    WindowResizeHandles { anchors.fill: parent; z: 100 }
    Shortcut { sequence: "Alt+F4"; onActivated: desktopWindow.close() }
    Shortcut { sequence: "Alt+F10"; onActivated: desktopWindow.toggleMaximized() }
}
