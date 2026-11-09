import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../design"

ColumnLayout {
    id: pane
    property bool expanded: true
    visible: jobs.count > 0
    spacing: 4
    RowLayout {
        Layout.fillWidth: true
        MButton { text: pane.expanded ? qsTr("收起下载任务") : qsTr("展开下载任务"); variant: "text"; onClicked: pane.expanded = !pane.expanded }
        MLabel { text: qsTr("%1 项进行中").arg(speechLibrary.downloadCount); role: "supporting"; font.pixelSize: 12 }
        MButton { text: qsTr("清除已结束"); variant: "text"; onClicked: speechLibrary.downloadJobs.clearFinished() }
    }
    ScrollView {
        visible: pane.expanded
        Layout.fillWidth: true
        Layout.preferredHeight: Math.min(206, jobs.contentHeight)
        clip: true
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ListView {
            id: jobs
            objectName: "speechDownloadJobs"
            model: speechLibrary.downloadJobs
            boundsBehavior: Flickable.StopAtBounds
            spacing: 4
            delegate: Rectangle {
                id: jobRow
                required property string jobId
                required property string name
                required property string task
                required property string language
                required property string state
                required property string phaseText
                required property string component
                required property real totalBytes
                required property real progress
                required property string transferText
                required property string errorText
                required property bool active
                width: ListView.view.width
                height: content.implicitHeight + 12
                color: AppTheme.surfaceContainerLow
                radius: 4
                ColumnLayout {
                    id: content
                    anchors.left: parent.left; anchors.right: parent.right
                    anchors.top: parent.top; anchors.margins: 6
                    spacing: 2
                    RowLayout {
                        Layout.fillWidth: true
                        MLabel { text: task + " · " + name; role: "label"; font.pixelSize: 13; maximumLineCount: 1; elide: Text.ElideRight }
                        MLabel { text: language.toUpperCase(); role: "supporting"; font.pixelSize: 11; Layout.fillWidth: false }
                        MButton { objectName: "cancelDownload-" + jobId; visible: jobRow.active; enabled: jobRow.state !== "cancelling"; text: qsTr("取消"); variant: "text"; implicitHeight: 28; onClicked: speechLibrary.downloadJobs.cancel(jobId) }
                        MButton { objectName: "retryDownload-" + jobId; visible: jobRow.state === "cancelled" || jobRow.state === "failed"; text: jobRow.state === "cancelled" ? qsTr("继续") : qsTr("重试"); variant: "text"; implicitHeight: 28; onClicked: speechLibrary.downloadJobs.retry(jobId) }
                    }
                    MLabel { objectName: "downloadComponent-" + jobId; text: phaseText + (component ? " · " + component : ""); role: "supporting"; font.pixelSize: 12; maximumLineCount: 1; elide: Text.ElideMiddle; Accessible.name: text }
                    ProgressBar { Layout.fillWidth: true; Layout.preferredHeight: 3; visible: active; indeterminate: totalBytes <= 0; value: progress }
                    MLabel { visible: active && transferText.length > 0; text: qsTr("当前文件：%1").arg(transferText); role: "supporting"; font.pixelSize: 11 }
                    MLabel { visible: errorText.length > 0; text: errorText; color: jobRow.state === "failed" ? AppTheme.error : AppTheme.colorOnSurfaceVariant; role: "supporting"; font.pixelSize: 12 }
                }
            }
        }
    }
}
