import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: summary
    required property real downloadMiB
    required property real requiredFreeMiB
    property bool explain: false
    readonly property string explanation: qsTr("安装空间预算约 %1，包含下载文件、解包和安装临时副本及安全余量，不代表最终磁盘占用或运行内存。下载量包含模型和缺少的共享组件；完整下载缓存可复用，估算未扣除断点文件。实际安装前会检查可用空间。").arg(summary.capacity(summary.requiredFreeMiB))
    Layout.fillWidth: true
    spacing: 3
    function capacity(mib) {
        return mib >= 1024 ? qsTr("%1 GiB").arg((mib / 1024).toFixed(2)) : qsTr("%1 MiB").arg(mib.toFixed(1))
    }
    RowLayout {
        Layout.fillWidth: true
        spacing: 6
        MLabel {
            id: capacityLabel
            objectName: "speechPreparationSummary"
            text: qsTr("需下载约 %1").arg(summary.capacity(summary.downloadMiB))
            role: "supporting"; font.pixelSize: 12
            activeFocusOnTab: true
            Accessible.description: summary.explanation
            ToolTip.visible: capacityHover.hovered || activeFocus
            ToolTip.text: summary.explanation
            ToolTip.delay: 650
            HoverHandler { id: capacityHover }
        }
        MHelpButton {
            visible: summary.explain
            text: qsTr("容量说明")
            helpText: summary.explanation
        }
    }
}
