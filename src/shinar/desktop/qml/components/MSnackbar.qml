import QtQuick
import QtQuick.Controls
import "../design"

Popup {
    id: snackbar
    property string message: ""
    padding: 16
    closePolicy: Popup.CloseOnEscape
    contentItem: Label { text: snackbar.message; color: AppTheme.surface; wrapMode: Text.Wrap }
    background: Rectangle { radius: AppTheme.cardRadius; color: AppTheme.colorOnSurface }
    onOpened: timer.restart()
    Timer { id: timer; interval: 3500; onTriggered: snackbar.close() }
}
