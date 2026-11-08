import QtQuick
import QtQuick.Layouts
import "../design"

ColumnLayout {
    property string selectedTab: "threads"
    property bool allowStart: true
    spacing: 16
    RowLayout {
        Layout.fillWidth: true
        MLabel { text: workspace.material.title || ""; font.family: AppTheme.readingFont; font.pixelSize: 23; maximumLineCount: 1; elide: Text.ElideRight }
        MButton { text: workspace.material.range || qsTr("已读范围"); variant: "text"; onClicked: if (selectedTab !== "scope") workspace.openScope() }
        MButton { visible: allowStart; text: qsTr("+ 新对话"); enabled: !workspace.threadLocked; onClicked: workspace.newThreadPage() }
    }
    RowLayout {
        MButton { text: qsTr("对话"); variant: selectedTab === "threads" ? "tonal" : "text"; onClicked: workspace.navigate("material") }
        MButton { text: qsTr("已读范围"); variant: selectedTab === "scope" ? "tonal" : "text"; onClicked: if (selectedTab !== "scope") workspace.openScope() }
        MButton { text: qsTr("参考"); variant: selectedTab === "reference" ? "tonal" : "text"; onClicked: workspace.navigate("reference") }
    }
}
