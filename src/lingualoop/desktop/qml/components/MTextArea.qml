import QtQuick
import QtQuick.Controls.Basic as Basic
import "../design"

Basic.TextArea {
    implicitHeight: 120
    wrapMode: TextEdit.Wrap
    selectByMouse: true
    font.family: AppTheme.uiFont
    font.pixelSize: AppTheme.bodyLarge
    color: AppTheme.colorOnSurface
    placeholderTextColor: AppTheme.colorOnSurfaceVariant
    padding: 10
    selectionColor: AppTheme.primaryContainer
    selectedTextColor: AppTheme.colorOnSurface
    background: Rectangle { color: AppTheme.dark ? AppTheme.surfaceContainer : "#FBF8F0"; radius: 4; border.width: 1; border.color: parent.activeFocus ? AppTheme.primary : AppTheme.outlineVariant }
    Accessible.name: placeholderText
}
