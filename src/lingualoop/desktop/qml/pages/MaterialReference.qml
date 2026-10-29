import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../design"
import "../components"

ColumnLayout {
    id: page
    property bool expanded: false
    spacing: 20
    RowLayout {
        Layout.fillWidth: true
        MButton { text: qsTr("‹ 返回"); variant: "text"; onClicked: workspace.navigate("material") }
        Item { Layout.fillWidth: true }
        MButton { text: qsTr("继续整理"); variant: "outlined"; enabled: !workspace.threadLocked && !!workspace.material.confirmed; onClicked: workspace.prepareBrowsing(false) }
        MButton { text: qsTr("重新分析"); variant: "text"; enabled: !workspace.threadLocked && !!workspace.material.confirmed; onClicked: workspace.prepareBrowsing(true) }
    }
    ScrollView {
        Layout.fillWidth: true; Layout.fillHeight: true; contentWidth: availableWidth; clip: true
        ColumnLayout {
            width: parent.width; spacing: 20
            MLabel { text: workspace.reference.status; role: "supporting" }
            MLabel { text: workspace.reference.summary; font.family: AppTheme.readingFont; maximumLineCount: page.expanded ? 2147483647 : 7; elide: Text.ElideRight }
            MButton { visible: workspace.reference.summary.length > 300; text: page.expanded ? qsTr("收起") : qsTr("展开"); variant: "text"; onClicked: page.expanded = !page.expanded }
            Repeater { model: workspace.reference.outline; MLabel { required property string modelData; text: modelData } }
        }
    }
}
