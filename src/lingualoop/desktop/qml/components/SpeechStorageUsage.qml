import QtQuick
import QtQuick.Layouts

ColumnLayout {
    id: summary
    required property var usage
    property bool collapsible: false
    property bool expanded: false
    property string explanation: ""
    Layout.fillWidth: true
    spacing: 3
    function capacity(mib) {
        return mib >= 1024 ? qsTr("%1 GiB").arg((mib / 1024).toFixed(2)) : qsTr("%1 MiB").arg(mib.toFixed(1))
    }
    RowLayout {
        Layout.fillWidth: true
        MLabel {
            objectName: summary.objectName + "-total"
            text: summary.usage.totalMiB === undefined ? qsTr("正在统计本地语音文件…") : qsTr("本地语音文件共 %1%2").arg(summary.capacity(summary.usage.totalMiB)).arg(summary.usage.incomplete ? qsTr("（部分文件未能统计）") : "")
            role: "supporting"; font.pixelSize: 12
        }
        MButton { visible: summary.collapsible; text: summary.expanded ? qsTr("收起空间说明") : qsTr("空间说明"); variant: "text"; Layout.fillWidth: false; implicitHeight: 28; onClicked: summary.expanded = !summary.expanded }
    }
    MLabel {
        visible: summary.usage.totalMiB !== undefined && (!summary.collapsible || summary.expanded)
        text: qsTr("已安装资源 %1 · 下载与安装缓存 %2 · 其他 %3").arg(summary.capacity(summary.usage.installedMiB || 0)).arg(summary.capacity(summary.usage.cacheMiB || 0)).arg(summary.capacity(summary.usage.otherMiB || 0))
        role: "supporting"; font.pixelSize: 12
    }
    MLabel { visible: (!summary.collapsible || summary.expanded) && text.length > 0; text: summary.explanation; role: "supporting"; font.pixelSize: 12 }
}
