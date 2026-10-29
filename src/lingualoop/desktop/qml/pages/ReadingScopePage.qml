import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../design"
import "../components"

GridLayout {
    id: page
    columns: width >= 800 ? 2 : 1
    columnSpacing: 32; rowSpacing: 16
    SourceReader { scopeMode: true; Layout.fillWidth: true; Layout.fillHeight: true; Layout.row: page.columns === 2 ? 0 : 1; Layout.column: 0; onBack: workspace.navigate("material") }
    ScrollView {
        Layout.preferredWidth: page.columns === 2 ? 280 : -1; Layout.fillWidth: page.columns === 1
        Layout.fillHeight: page.columns === 2; Layout.preferredHeight: page.columns === 1 ? Math.min(320, fields.implicitHeight) : -1
        Layout.row: 0; Layout.column: page.columns === 2 ? 1 : 0
        contentWidth: availableWidth; clip: true
        ColumnLayout {
            id: fields
            width: parent.width; spacing: 22
            RowLayout {
                MButton { objectName: "readWholeMaterialButton"; text: "已读完"; variant: "outlined"; onClicked: workspace.markAllRead() }
                MButton { text: "返回"; variant: "text"; onClicked: workspace.navigate("material") }
            }
            ComboBox { id: method; Layout.fillWidth: true; model: ["点选末段", "末句定位", "大致进度"]; implicitHeight: 38; Accessible.name: "定位方式" }
            ColumnLayout { visible: method.currentIndex === 1; Layout.fillWidth: true; spacing: 12
                MTextArea { id: sentence; Layout.fillWidth: true; implicitHeight: 90; placeholderText: "已读到的最后一句" }
                MButton { text: "定位"; variant: "outlined"; onClicked: workspace.locateSentence(sentence.text) }
            }
            RowLayout { visible: method.currentIndex === 2
                SpinBox { id: percent; from: 1; to: 100; value: 50; editable: true; Accessible.name: "已读百分比" }
                MLabel { text: "%"; Layout.fillWidth: false }
                MButton { text: "定位"; variant: "outlined"; onClicked: workspace.locatePercent(percent.value) }
            }
            MLabel { visible: workspace.pendingEnd > 0; text: workspace.scopeQuote; font.family: AppTheme.readingFont; maximumLineCount: 5; elide: Text.ElideLeft }
            MButton { objectName: "saveScopeButton"; text: "保存已读范围"; enabled: workspace.pendingEnd > 0 && !learningViewModel.busy; onClicked: workspace.saveScope() }
        }
    }
}
