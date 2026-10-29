import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../design"

Rectangle {
    id: sidebar
    property bool collapsed: false
    signal activated()
    color: AppTheme.surfaceContainerLow
    function go(route) { workspace.navigate(route); activated() }
    ColumnLayout {
        anchors.fill: parent; anchors.margins: sidebar.collapsed ? 6 : 10
        spacing: 4
        MLabel { visible: !sidebar.collapsed; text: "LinguaLoop"; font.family: AppTheme.readingFont; font.pixelSize: 23; Layout.topMargin: 2; Layout.bottomMargin: 14 }
        MButton {
            objectName: "nav0"
            Layout.fillWidth: true
            text: sidebar.collapsed ? "‹" : workspace.route === "settings" ? "‹  返回工作区" : "材料库"
            variant: workspace.route === "library" ? "tonal" : "text"
            icon.source: sidebar.collapsed || workspace.route !== "settings" ? "../assets/illustrated/book.png" : ""
            onClicked: sidebar.go("library")
            Accessible.name: "材料库"
        }
        MButton { visible: workspace.route !== "settings"; text: sidebar.collapsed ? "+" : "+  导入材料"; Layout.fillWidth: true; variant: workspace.route === "import" ? "tonal" : "text"; onClicked: sidebar.go("import"); Accessible.name: "导入材料" }
        ScrollView {
            Layout.fillWidth: true; Layout.fillHeight: true
            contentWidth: availableWidth; clip: true
            ColumnLayout {
                width: parent.width; spacing: 1
                Repeater {
                    model: workspace.route === "settings" ? [
                        {key:"appearance", label:"外观"}, {key:"learning", label:"学习偏好"},
                        {key:"services", label:"模型与服务"}, {key:"audio", label:"音频设备"},
                        {key:"local", label:"本地语音模型"}, {key:"data", label:"数据与隐私"}] : []
                    MButton {
                        required property var modelData
                        objectName: "settings-" + modelData.key
                        Layout.fillWidth: true
                        text: sidebar.collapsed ? modelData.label.slice(0,1) : modelData.label
                        variant: workspace.settingsCategory === modelData.key ? "tonal" : "text"
                        onClicked: { workspace.setCategory(modelData.key); sidebar.activated() }
                    }
                }
                Repeater {
                    model: !sidebar.collapsed && workspace.route !== "settings" ? workspace.materials : []
                    ColumnLayout {
                        id: materialNode
                        required property var modelData
                        Layout.fillWidth: true; Layout.topMargin: 8; spacing: 1
                        RowLayout {
                            Layout.fillWidth: true; spacing: 0
                            MButton { text: materialNode.modelData.expanded ? "⌄" : "›"; variant: "text"; implicitWidth: 24; leftPadding: 0; rightPadding: 0; Accessible.name: "展开 " + materialNode.modelData.title; onClicked: workspace.toggleMaterial(materialNode.modelData.id) }
                            MButton {
                                Layout.fillWidth: true; Layout.minimumWidth: 0
                                text: materialNode.modelData.title; variant: "text"; leftPadding: 3; rightPadding: 3
                                contentItem: Text { text: parent.text; font: parent.font; color: AppTheme.colorOnSurface; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter }
                                onClicked: { workspace.browseMaterial(materialNode.modelData.id); sidebar.activated() }
                                ToolTip.visible: hovered; ToolTip.text: text
                            }
                        }
                        Repeater {
                            model: materialNode.modelData.expanded ? materialNode.modelData.threads.slice(0,5) : []
                            MButton {
                                required property var modelData
                                Layout.fillWidth: true; Layout.leftMargin: 20; Layout.minimumWidth: 0
                                text: modelData.title; variant: modelData.selected && workspace.route === "chat" ? "tonal" : "text"
                                leftPadding: 8; rightPadding: 6; font.pixelSize: 12
                                enabled: !workspace.threadLocked
                                contentItem: Text { text: parent.text; font: parent.font; color: AppTheme.colorOnSurface; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter }
                                ToolTip.visible: hovered; ToolTip.text: text
                                onClicked: { workspace.openThread(modelData.id); sidebar.activated() }
                            }
                        }
                        MButton { visible: materialNode.modelData.expanded; Layout.leftMargin: 20; text: "+ 新对话"; variant: "text"; enabled: !workspace.threadLocked; onClicked: { workspace.browseMaterial(materialNode.modelData.id); workspace.newThreadPage(); sidebar.activated() } }
                    }
                }
            }
        }
        MButton { objectName: "nav2"; Layout.fillWidth: true; text: sidebar.collapsed ? "" : "表达复习"; icon.source: "../assets/illustrated/review.png"; variant: workspace.route === "queue" ? "tonal" : "text"; onClicked: sidebar.go("queue"); Accessible.name: "表达复习" }
        MButton { Layout.fillWidth: true; text: sidebar.collapsed ? "···" : "更多"; variant: "text"; onClicked: sidebar.go("more"); Accessible.name: "更多" }
        MButton { objectName: "nav3"; Layout.fillWidth: true; text: sidebar.collapsed ? "" : "设置"; icon.source: "../assets/illustrated/settings.png"; variant: workspace.route === "settings" ? "tonal" : "text"; onClicked: sidebar.go("settings"); Accessible.name: "设置" }
    }
}
