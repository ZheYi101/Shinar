import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "../design"
import "../components"

ScrollView {
    id: page
    objectName: "speechStoragePage"
    contentWidth: availableWidth
    clip: true
    property bool initialized: false
    property bool awaitingPreview: false
    Component.onCompleted: initialized = true
    onVisibleChanged: if (visible && initialized && !speechStorage.busy) speechStorage.refresh()

    ColumnLayout {
        width: Math.min(page.availableWidth, 800)
        x: (page.availableWidth - width) / 2
        spacing: 16
        RowLayout {
            Layout.fillWidth: true
            MLabel { text: qsTr("模型与运行环境位置"); Layout.fillWidth: true }
            MButton {
                objectName: "chooseSpeechStorage"
                text: qsTr("更改位置")
                variant: "outlined"
                enabled: speechStorage.canChangeLocation
                onClicked: folder.open()
            }
        }
        MLabel {
            objectName: "speechStoragePath"
            Layout.fillWidth: true
            text: speechStorage.location
            wrapMode: Text.WrapAnywhere
        }
        MLabel {
            visible: text.length > 0
            Layout.fillWidth: true
            text: speechStorage.locationExplanation
            role: "supporting"
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: AppTheme.outlineVariant }
        RowLayout {
            Layout.fillWidth: true
            MLabel { text: qsTr("文件合计 %1").arg(speechStorage.totalSize); Layout.fillWidth: true }
            MButton { objectName: "refreshSpeechStorage"; text: qsTr("重新扫描"); variant: "text"; enabled: !speechStorage.busy && !speechStorage.restartRequired; onClicked: speechStorage.refresh() }
            MHelpButton {
                objectName: "speechStorageHelp"
                text: qsTr("空间说明")
                helpText: qsTr("按文件大小统计，硬链接只计一次；不等同于磁盘分配的空间。可清理量会排除仍被运行环境引用的硬链接和未完成下载。清理后重新安装或修复时可能需要再次下载。这里不包含学习资料、对话历史或连续通话组件；更改位置不会搬动它们。")
            }
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 0
            Repeater {
                model: speechStorage.categories
                SettingsValue { required property var modelData; Layout.fillWidth: true; label: modelData.label; value: modelData.size }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            MLabel { text: qsTr("可清理约 %1").arg(speechStorage.cacheSize); Layout.fillWidth: true }
            MButton {
                objectName: "cleanSpeechCache"
                text: qsTr("清理缓存…")
                variant: "outlined"
                enabled: !speechStorage.busy && !speechStorage.restartRequired && !speechStorage.inventory.incomplete && (speechStorage.inventory.reclaimableBytes || 0) > 0
                onClicked: cleanDialog.open()
            }
        }
        MLabel {
            objectName: "speechStorageStatus"
            Layout.fillWidth: true
            visible: text.length > 0
            text: speechStorage.status
            Accessible.role: Accessible.AlertMessage
        }
        RowLayout {
            visible: speechStorage.busy
            Layout.fillWidth: true
            ProgressBar { Layout.fillWidth: true; indeterminate: true }
            MButton { objectName: "cancelSpeechStorage"; text: qsTr("取消"); variant: "text"; onClicked: speechStorage.cancel() }
        }
    }
    FolderDialog {
        id: folder
        objectName: "speechStorageFolder"
        title: qsTr("选择新的空文件夹")
        onAccepted: {
            page.awaitingPreview = true
            speechStorage.previewMigration(selectedFolder.toString())
        }
    }
    MDialog {
        id: cleanDialog
        objectName: "speechCacheConfirmation"
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(520, Overlay.overlay ? Overlay.overlay.width - 32 : 360)
        implicitHeight: 260
        title: qsTr("清理约 %1 缓存？").arg(speechStorage.cacheSize)
        standardButtons: Dialog.Ok | Dialog.Cancel
        contentItem: MLabel {
            text: qsTr("删除已完成的下载文件和可再生成的安装缓存。保留已安装模型、运行环境、未完成下载和学习资料。重新安装或修复时可能需要再次下载。")
        }
        onAccepted: speechStorage.cleanCaches()
    }
    MDialog {
        id: migrationDialog
        objectName: "speechStorageConfirmation"
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(560, Overlay.overlay ? Overlay.overlay.width - 32 : 360)
        implicitHeight: Math.min(410, Overlay.overlay ? Overlay.overlay.height - 32 : 410)
        title: qsTr("迁移模型与运行环境？")
        standardButtons: Dialog.Ok | Dialog.Cancel
        contentItem: ScrollView {
            contentWidth: availableWidth; clip: true
            MLabel {
                width: parent.width
                wrapMode: Text.WrapAnywhere
                text: qsTr("新位置：%1\n\n复制模型后会重建并验证运行环境；可能需要下载缺少的安装文件。成功后重启生效。原位置保留，取消或失败不会切换位置。\n\n目标需预留约 %2 GiB。").arg(speechStorage.migration.destination || "").arg(((speechStorage.migration.requiredBytes || 0) / 1073741824).toFixed(2))
            }
        }
        onAccepted: { page.awaitingPreview = false; speechStorage.migrate() }
        onRejected: { page.awaitingPreview = false; speechStorage.clearMigration() }
    }
    Connections {
        target: speechStorage
        function onChanged() {
            if (page.awaitingPreview && !speechStorage.busy && speechStorage.migration.destination)
                migrationDialog.open()
            else if (page.awaitingPreview && !speechStorage.busy)
                page.awaitingPreview = false
        }
    }
}
