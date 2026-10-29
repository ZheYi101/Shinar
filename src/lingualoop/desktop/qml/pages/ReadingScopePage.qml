import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../design"
import "../components"

ColumnLayout {
    spacing: 16
    MaterialHeader { Layout.fillWidth: true; selectedTab: "scope"; allowStart: false }
    GridLayout {
        id: page
        Layout.fillWidth: true; Layout.fillHeight: true
        columns: width >= 800 ? 2 : 1
        columnSpacing: 32; rowSpacing: 16
        SourceReader { scopeMode: true; Layout.fillWidth: true; Layout.fillHeight: true; Layout.row: page.columns === 2 ? 0 : 1; Layout.column: 0; onBack: workspace.cancelScope() }
        ColumnLayout {
            Layout.preferredWidth: page.columns === 2 ? 280 : -1; Layout.fillWidth: page.columns === 1
            Layout.fillHeight: page.columns === 2; Layout.preferredHeight: page.columns === 1 ? Math.min(page.height * 0.46, fields.implicitHeight + 52) : -1
            Layout.minimumHeight: page.columns === 1 ? 190 : 0
            Layout.row: 0; Layout.column: page.columns === 2 ? 1 : 0
            spacing: 12
            ScrollView {
                objectName: "scopeControlsScroll"
                Layout.fillWidth: true; Layout.fillHeight: true
                contentWidth: availableWidth; clip: true
                ColumnLayout {
                    id: fields
                    width: parent.width; spacing: 20
                    RowLayout {
                        MButton { objectName: "readWholeMaterialButton"; text: qsTr("已读完"); variant: "outlined"; onClicked: workspace.markAllRead() }
                        MButton { text: qsTr("返回"); variant: "text"; onClicked: workspace.cancelScope() }
                    }
                    MComboBox { id: method; Layout.fillWidth: true; model: [qsTr("点选末段"), qsTr("末句定位"), qsTr("大致进度")]; implicitHeight: 38; Accessible.name: qsTr("定位方式") }
                    ColumnLayout { visible: method.currentIndex === 1; Layout.fillWidth: true; spacing: 12
                        MTextArea { id: sentence; Layout.fillWidth: true; implicitHeight: 90; placeholderText: qsTr("已读到的最后一句") }
                        MButton { text: qsTr("定位"); variant: "outlined"; onClicked: workspace.locateSentence(sentence.text) }
                    }
                    RowLayout { visible: method.currentIndex === 2
                        MSpinBox { id: percent; from: 1; to: 100; value: 50; editable: true; Accessible.name: qsTr("已读百分比") }
                        MLabel { text: "%"; Layout.fillWidth: false }
                        MButton { text: qsTr("定位"); variant: "outlined"; onClicked: workspace.locatePercent(percent.value) }
                    }
                    MLabel { visible: workspace.pendingEnd > 0; text: workspace.scopeQuote; font.family: workspace.sourceLanguage === "japanese" ? AppTheme.japaneseReadingFont : AppTheme.readingFont; maximumLineCount: page.columns === 2 ? 5 : 2; elide: Text.ElideLeft }
                }
            }
            MButton { objectName: "saveScopeButton"; text: qsTr("保存已读范围"); enabled: workspace.pendingEnd > 0 && !learningViewModel.busy; onClicked: workspace.saveScope() }
        }
    }
}
