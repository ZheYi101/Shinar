import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "design"
import "components"
import "pages"

Item {
    id: root
    property int currentPage: workspace.route === "chat" ? 1 : workspace.route === "review" || workspace.route === "queue" ? 2 : workspace.route === "settings" ? 3 : 0
    readonly property bool compact: width < 600
    readonly property int sidebarWidth: workspace.collapsed ? 56 : width < 1100 ? 192 : 208
    onCurrentPageChanged: {
        const route = currentPage === 1 ? "chat" : currentPage === 2 ? "review" : currentPage === 3 ? "settings" : "library"
        if (currentPage !== (workspace.route === "chat" ? 1 : workspace.route === "review" || workspace.route === "queue" ? 2 : workspace.route === "settings" ? 3 : 0)) workspace.navigate(route)
    }
    Rectangle { anchors.fill: parent; color: AppTheme.surface }
    RowLayout {
        anchors.fill: parent; spacing: 0
        WorkspaceSidebar { visible: !root.compact; Layout.preferredWidth: root.sidebarWidth; Layout.fillHeight: true; collapsed: workspace.collapsed }
        ColumnLayout {
            Layout.fillWidth: true; Layout.fillHeight: true; spacing: 0
            WindowTitleBar { Layout.fillWidth: true; Layout.preferredHeight: 30; onToggleSidebar: root.compact ? drawer.open() : workspace.toggleSidebar(); onNavigate: page => workspace.navigate(page === 3 ? "settings" : "review") }
            ProgressBar { visible: learningViewModel.busy; Layout.fillWidth: true; Layout.preferredHeight: 2; indeterminate: true }
            RowLayout {
                visible: learningViewModel.errorMessage.length > 0 || workspace.error.length > 0
                Layout.fillWidth: true; Layout.leftMargin: 20; Layout.rightMargin: 12; spacing: 8
                MLabel { text: workspace.error || learningViewModel.errorMessage; color: AppTheme.error; maximumLineCount: 3; elide: Text.ElideRight; Accessible.role: Accessible.AlertMessage }
                MButton { visible: learningViewModel.canRetryOperation; text: "重试"; variant: "text"; enabled: !learningViewModel.busy; onClicked: learningViewModel.retryOperation() }
                MIconButton { symbol: "close"; label: "关闭提示"; onClicked: { learningViewModel.dismissError(); workspace.navigate(workspace.route) } }
            }
            StackLayout {
                Layout.fillWidth: true; Layout.fillHeight: true
                currentIndex: ["library","material","import","scope","new","chat","review","queue","settings","more"].indexOf(workspace.route)
                Item { LibraryPage { anchors.fill: parent; anchors.margins: root.compact ? 12 : 24 } }
                Item { MaterialSpace { anchors.fill: parent; anchors.margins: root.compact ? 12 : 24 } }
                Item { ImportPage { anchors.fill: parent; anchors.margins: root.compact ? 12 : 28 } }
                Item { ReadingScopePage { anchors.fill: parent; anchors.margins: root.compact ? 8 : 20 } }
                Item { NewThreadPage { anchors.fill: parent; anchors.margins: root.compact ? 12 : 28 } }
                ConversationPage { onOpenMaterials: workspace.navigate("library") }
                Item { ReviewPage { anchors.fill: parent; anchors.margins: root.compact ? 12 : 28 } }
                Item { ReviewPage { queueOnly: true; anchors.fill: parent; anchors.margins: root.compact ? 12 : 28 } }
                Item { SettingsPage { anchors.fill: parent; anchors.margins: root.compact ? 12 : 28 } }
                ColumnLayout {
                    Layout.margins: 28
                    MButton { text: "表达复习"; variant: "text"; onClicked: workspace.navigate("queue") }
                    MButton { text: "本地语音模型"; variant: "text"; onClicked: { workspace.setCategory("local"); workspace.navigate("settings") } }
                    Item { Layout.fillHeight: true }
                }
            }
        }
    }
    Drawer { id: drawer; width: Math.min(root.width * 0.8, 260); height: root.height; WorkspaceSidebar { anchors.fill: parent; onActivated: drawer.close() } }
    Connections { target: workspace; function onChanged() { root.currentPage = workspace.route === "chat" ? 1 : workspace.route === "review" || workspace.route === "queue" ? 2 : workspace.route === "settings" ? 3 : 0 } }
    Shortcut { sequence: "Ctrl+1"; onActivated: workspace.navigate("library") }
    Shortcut { sequence: "Ctrl+2"; onActivated: workspace.navigate("chat") }
    Shortcut { sequence: "Ctrl+,"; onActivated: workspace.navigate("settings") }
}
