import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../design"

MCard {
    id: card
    property var review
    property bool answerSubmitted: false
    MLabel { text: card.review.prompt; role: "title" }
    MLabel { text: card.review.context || ""; role: "supporting"; visible: text.length > 0 }
    MTextField { id: answerInput; Layout.fillWidth: true; placeholderText: qsTr("先尝试回忆或表达") }
    MButton { text: qsTr("提交并查看参考"); variant: "tonal"; enabled: answerInput.text.trim().length > 0; onClicked: card.answerSubmitted = true }
    MLabel { visible: card.answerSubmitted; text: card.answerSubmitted ? qsTr("参考答案 %1").arg(card.review.answer) : "" }
    Flow {
        visible: card.answerSubmitted
        Layout.fillWidth: true; spacing: AppTheme.gapSmall
        Repeater {
            model: [{label: qsTr("再练一次"), value: "again"}, {label: qsTr("有点困难"), value: "hard"}, {label: qsTr("顺利想起"), value: "good"}, {label: qsTr("很轻松"), value: "easy"}]
            MButton {
                required property var modelData
                text: modelData.label; variant: "tonal"
                enabled: !learningViewModel.busy
                onClicked: learningViewModel.reviewOutcome(card.review.id, modelData.value, answerInput.text)
            }
        }
    }
    Flow {
        Layout.fillWidth: true; spacing: AppTheme.gapSmall
        MButton { text: qsTr("暂停"); variant: "text"; enabled: !learningViewModel.busy; onClicked: learningViewModel.updateReviewStatus(card.review.id, "paused") }
        MButton { text: qsTr("忽略"); variant: "text"; enabled: !learningViewModel.busy; onClicked: learningViewModel.updateReviewStatus(card.review.id, "ignored") }
        MButton { text: qsTr("归档"); variant: "text"; enabled: !learningViewModel.busy; onClicked: learningViewModel.updateReviewStatus(card.review.id, "archived") }
    }
}
