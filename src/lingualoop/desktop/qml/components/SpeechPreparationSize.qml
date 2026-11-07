import QtQuick
import QtQuick.Layouts

ColumnLayout {
    id: summary
    required property real downloadMiB
    required property real requiredFreeMiB
    property bool explain: false
    Layout.fillWidth: true
    spacing: 3
    function capacity(mib) {
        return mib >= 1024 ? qsTr("%1 GiB").arg((mib / 1024).toFixed(2)) : qsTr("%1 MiB").arg(mib.toFixed(1))
    }
    MLabel {
        text: qsTr("预计下载 %1 · 安装需可用空间 %2").arg(summary.capacity(summary.downloadMiB)).arg(summary.capacity(summary.requiredFreeMiB))
        role: "supporting"; font.pixelSize: 12
    }
    MLabel {
        visible: summary.explain
        text: qsTr("下载量包含缺少的共享组件；可用空间含安装临时文件和余量，不是最终硬盘占用或运行内存。")
        role: "supporting"; font.pixelSize: 12
    }
}
