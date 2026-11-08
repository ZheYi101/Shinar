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
    PaperTexture { anchors.fill: parent }
    ColumnLayout {
        anchors.fill: parent; anchors.margins: sidebar.collapsed ? 6 : 10
        spacing: 3
        RowLayout {
            Layout.fillWidth: true; Layout.preferredHeight: 46; Layout.bottomMargin: 10
            Image { source: "../../assets/app-icon.svg"; Layout.preferredWidth: 26; Layout.preferredHeight: 26; Layout.leftMargin: 6; Accessible.name: "Shinar" }
            MLabel { visible: !sidebar.collapsed; text: "Shinar"; font.pixelSize: 16; font.weight: Font.DemiBold }
        }
        SidebarItem {
            objectName: "nav0"
            Layout.fillWidth: true
            collapsed: sidebar.collapsed
            text: workspace.route === "settings" ? qsTr("返回工作区") : qsTr("材料库")
            selected: workspace.route === "library"
            symbol: workspace.route === "settings" ? "arrow_back" : "library_books"
            onClicked: sidebar.go("library")
            Accessible.name: qsTr("材料库")
        }
        SidebarItem { visible: workspace.route !== "settings"; text: qsTr("导入材料"); symbol: "add"; collapsed: sidebar.collapsed; Layout.fillWidth: true; selected: workspace.route === "import"; onClicked: sidebar.go("import") }
        MLabel { visible: !sidebar.collapsed; text: workspace.route === "settings" ? qsTr("设置") : qsTr("材料与对话"); role: "supporting"; font.pixelSize: 11; Layout.leftMargin: 10; Layout.topMargin: 18; Layout.bottomMargin: 6 }
        ScrollView {
            Layout.fillWidth: true; Layout.fillHeight: true
            contentWidth: availableWidth; clip: true
            ColumnLayout {
                width: parent.width; spacing: 1
                Repeater {
                    model: workspace.route === "settings" ? [
                        {key:"appearance", label:qsTr("外观")}, {key:"learning", label:qsTr("学习偏好")},
                        {key:"services", label:qsTr("模型与服务")}, {key:"audio", label:qsTr("音频设备")},
                        {key:"local", label:qsTr("本地语音模型")}, {key:"data", label:qsTr("数据与隐私")}] : []
                    SidebarItem {
                        required property var modelData
                        objectName: "settings-" + modelData.key
                        Layout.fillWidth: true
                        collapsed: sidebar.collapsed
                        text: modelData.label
                        symbol: ({appearance:"settings",learning:"library_books",services:"chat_bubble",audio:"mic",local:"play_arrow",data:"history"})[modelData.key]
                        selected: workspace.settingsCategory === modelData.key
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
                            MButton { text: materialNode.modelData.expanded ? "⌄" : "›"; variant: "text"; implicitWidth: 24; leftPadding: 0; rightPadding: 0; Accessible.name: qsTr("展开 %1").arg(materialNode.modelData.title); onClicked: workspace.toggleMaterial(materialNode.modelData.id) }
                            MButton {
                                Layout.fillWidth: true; Layout.minimumWidth: 0
                                text: materialNode.modelData.title; variant: "text"; leftPadding: 3; rightPadding: 3
                                contentItem: Text { text: parent.text; font: parent.font; color: AppTheme.colorOnSurface; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter }
                                onClicked: { workspace.browseMaterial(materialNode.modelData.id); sidebar.activated() }
                                ToolTip.visible: hovered; ToolTip.text: text; ToolTip.delay: 650
                            }
                        }
                        Repeater {
                            model: materialNode.modelData.expanded ? materialNode.modelData.threads.slice(0,5) : []
                            MButton {
                                required property var modelData
                                Layout.fillWidth: true; Layout.leftMargin: 20; Layout.minimumWidth: 0
                                text: modelData.title; variant: modelData.selected && workspace.route === "chat" ? "tonal" : "text"
                                leftPadding: 8; rightPadding: 6; font.pixelSize: 13; implicitHeight: 32
                                enabled: !workspace.threadLocked
                                contentItem: Text { text: parent.text; font: parent.font; color: AppTheme.colorOnSurface; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter }
                                ToolTip.visible: hovered; ToolTip.text: text; ToolTip.delay: 650
                                background: Rectangle {
                                    radius: 7
                                    color: parent.variant === "tonal" ? Qt.alpha(AppTheme.primary,0.13) : parent.down ? Qt.alpha(AppTheme.colorOnSurface,0.13) : parent.hovered ? Qt.alpha(AppTheme.colorOnSurface,0.065) : "transparent"
                                    Behavior on color { ColorAnimation { duration: AppTheme.motionFast } }
                                }
                                onClicked: { workspace.openThread(modelData.id); sidebar.activated() }
                            }
                        }
                        MButton { visible: materialNode.modelData.expanded; Layout.leftMargin: 20; horizontalAlignment: Text.AlignLeft; text: qsTr("+ 新对话"); variant: "text"; enabled: !workspace.threadLocked; onClicked: { workspace.browseMaterial(materialNode.modelData.id); workspace.newThreadPage(); sidebar.activated() } }
                    }
                }
            }
        }
        SidebarItem { objectName: "nav3"; Layout.fillWidth: true; Layout.topMargin: 8; Layout.bottomMargin: 4; collapsed: sidebar.collapsed; text: qsTr("设置"); symbol: "settings"; selected: workspace.route === "settings"; onClicked: sidebar.go("settings") }
    }
}
