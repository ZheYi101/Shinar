import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs as Dialogs
import "../design"
import "../components"

ScrollView {
    id: page
    objectName: "reviewScroll"
    property bool expanded: false
    property bool queueOnly: false
    clip: true
    contentWidth: availableWidth
    ColumnLayout {
        width: page.availableWidth
        spacing: AppTheme.sectionGap
        RowLayout { visible: !page.queueOnly
            MButton { text: qsTr("‹ 对话"); variant: "text"; onClicked: workspace.navigate("chat") }
        }
        MCard {
            visible: !page.queueOnly
            color: "transparent"; padding: 0
            MLabel { text: qsTr("本轮小结"); role: "title" }
            MLabel { text: learningViewModel.reviewSummary }
            MButton { text: qsTr("导出会话"); variant: "text"; enabled: learningViewModel.hasSession && !learningViewModel.busy; onClicked: exportDialog.open() }
        }
        Repeater {
            model: page.queueOnly ? [] : learningViewModel.feedbackItems
            MCard {
                required property var modelData
                MLabel { text: modelData.original + " → " + modelData.corrected; role: "title" }
                MLabel { text: modelData.explanation; role: "supporting" }
            }
        }
        MLabel { text: qsTr("今日到期 %1 项").arg(learningViewModel.dueReviewCount); role: "title" }
        MLabel { visible: learningViewModel.reviewItems.length === 0; text: qsTr("暂无待复习项"); role: "supporting" }
        Repeater {
            model: page.expanded ? learningViewModel.reviewItems : learningViewModel.reviewItems.slice(0, 3)
            ReviewCard { required property var modelData; review: modelData }
        }
        MButton { visible: learningViewModel.reviewItems.length > 3; text: page.expanded ? qsTr("收起更多复习") : qsTr("展开全部复习"); variant: "text"; onClicked: page.expanded = !page.expanded }
        Item { Layout.preferredHeight: 16 }
    }
    Dialogs.FileDialog {
        id: exportDialog
        title: qsTr("导出会话")
        fileMode: Dialogs.FileDialog.SaveFile
        defaultSuffix: "json"
        nameFilters: ["JSON (*.json)"]
        onAccepted: learningViewModel.exportSession(selectedFile.toString())
    }
}
