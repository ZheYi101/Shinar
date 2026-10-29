import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import "../design"

TextArea {
    implicitHeight: 120
    wrapMode: TextEdit.Wrap
    selectByMouse: true
    font.family: AppTheme.uiFont
    font.pixelSize: AppTheme.bodyLarge
    color: AppTheme.colorOnSurface
    placeholderTextColor: AppTheme.colorOnSurfaceVariant
    padding: 10
    background: Rectangle { color: AppTheme.dark ? AppTheme.surfaceContainer : "#FBF8F0"; radius: 4; border.width: 1; border.color: parent.activeFocus ? AppTheme.primary : AppTheme.outlineVariant }
    Material.containerStyle: Material.Outlined
    Material.accent: AppTheme.primary
    Accessible.name: placeholderText
}
