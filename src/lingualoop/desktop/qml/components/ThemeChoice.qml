import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../design"

SettingsRow {
    label: qsTr("外观模式")
    Row {
        spacing: 8
        Repeater {
            model: [{code: "light", label: qsTr("浅色")}, {code: "dark", label: qsTr("深色")}, {code: "system", label: qsTr("系统")}]
            AbstractButton {
                id: tile
                required property var modelData
                objectName: "theme-" + modelData.code
                readonly property bool selected: learningViewModel.preferences.themeMode === modelData.code
                implicitWidth: 86; implicitHeight: 84
                hoverEnabled: true
                Accessible.name: modelData.label
                Accessible.role: Accessible.RadioButton
                Accessible.checked: selected
                onClicked: learningViewModel.preferences.setValue("themeMode", modelData.code)
                background: Rectangle {
                    radius: 5
                    color: AppTheme.dark ? AppTheme.surfaceContainer : "#FCF9F1"
                    border.color: tile.selected || tile.visualFocus ? AppTheme.primary : AppTheme.outlineVariant
                    border.width: tile.selected || tile.visualFocus ? 2 : 1
                }
                contentItem: Column {
                    spacing: 6
                    topPadding: 8
                    Rectangle {
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: 66; height: 39; radius: 2
                        color: tile.modelData.code === "dark" ? "#30352B" : "#F7F3E9"
                        Rectangle { width: 17; height: parent.height; color: tile.modelData.code === "dark" ? "#252920" : "#DFDACB" }
                        Rectangle { visible: tile.modelData.code === "system"; anchors.right: parent.right; width: 33; height: parent.height; color: "#30352B" }
                        Rectangle { x: 23; y: 10; width: 33; height: 3; color: "#A2AA96" }
                    }
                    Text { anchors.horizontalCenter: parent.horizontalCenter; text: tile.modelData.label; color: AppTheme.colorOnSurface; font.family: AppTheme.uiFont; font.pixelSize: 12 }
                }
            }
        }
    }
}
