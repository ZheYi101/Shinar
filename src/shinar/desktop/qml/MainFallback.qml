import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import "design"
import "components"

ApplicationWindow {
    readonly property var workspaceController: workspace
    flags: Qt.Window | Qt.FramelessWindowHint | Qt.WindowMinMaxButtonsHint
    visible: initialWindowVisible
    width: 1180; height: 780
    minimumWidth: 360; minimumHeight: 560
    title: "Shinar"
    Material.theme: AppTheme.dark ? Material.Dark : Material.Light
    Material.accent: AppTheme.primary
    Material.background: AppTheme.surface
    Material.foreground: AppTheme.colorOnSurface
    font.family: AppTheme.uiFont
    WorkbenchScaffold { anchors.fill: parent }
    WindowResizeHandles { anchors.fill: parent; z: 100 }
    Shortcut { sequence: "Alt+F4"; onActivated: desktopWindow.close() }
    Shortcut { sequence: "Alt+F10"; onActivated: desktopWindow.toggleMaximized() }
}
