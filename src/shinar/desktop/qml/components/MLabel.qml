import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../design"

Label {
    property string role: "body"
    Layout.fillWidth: true
    Layout.minimumWidth: 0
    color: role === "supporting" ? AppTheme.colorOnSurfaceVariant : AppTheme.colorOnSurface
    font.family: AppTheme.uiFont
    font.pixelSize: role === "headline" ? AppTheme.headlineMedium : role === "title" ? AppTheme.titleLarge : role === "label" || role === "supporting" ? AppTheme.bodyMedium : AppTheme.bodyLarge
    font.weight: role === "title" || role === "label" ? Font.Medium : Font.Normal
    wrapMode: Text.Wrap
    textFormat: Text.PlainText
    lineHeight: AppTheme.bodyLineHeight
}
