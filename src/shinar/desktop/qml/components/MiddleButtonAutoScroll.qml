import QtQuick
import QtQuick.Window
import "../design"

Item {
    id: root
    clip: true
    required property Flickable target
    readonly property bool scrolling: timer.running
    property point origin: Qt.point(0, 0)
    property real displacement: 0
    property var previousFocus: null
    property bool dragged: false
    property double lastTick: 0

    function start(x, y) {
        if (target.contentHeight <= target.height) return
        target.cancelFlick()
        origin = Qt.point(x, y)
        displacement = 0
        dragged = false
        previousFocus = Window.window ? Window.window.activeFocusItem : null
        forceActiveFocus(Qt.MouseFocusReason)
        lastTick = Date.now()
        timer.start()
    }

    function stop() {
        if (!scrolling) return
        timer.stop()
        displacement = 0
        if (activeFocus && previousFocus && previousFocus.visible && previousFocus.enabled)
            previousFocus.forceActiveFocus(Qt.OtherFocusReason)
        previousFocus = null
    }

    onVisibleChanged: if (!visible) stop()
    onEnabledChanged: if (!enabled) stop()
    onActiveFocusChanged: if (scrolling && !activeFocus) stop()
    Keys.onEscapePressed: function(event) { stop(); event.accepted = true }

    Connections {
        target: root.Window.window
        function onActiveChanged() { if (!target.active) root.stop() }
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: root.scrolling ? Qt.AllButtons : Qt.MiddleButton
        hoverEnabled: root.scrolling
        preventStealing: true
        cursorShape: root.scrolling ? Qt.SizeVerCursor : Qt.ArrowCursor
        onPressed: function(mouse) {
            if (root.scrolling) root.stop()
            else root.start(mouse.x, mouse.y)
        }
        onPositionChanged: function(mouse) {
            if (!root.scrolling) return
            root.displacement = mouse.y - root.origin.y
            if ((pressedButtons & Qt.MiddleButton) && Math.abs(root.displacement) > 12)
                root.dragged = true
        }
        onReleased: if (root.dragged) root.stop()
        onCanceled: root.stop()
        onExited: root.stop()
        onWheel: function(wheel) { root.stop(); wheel.accepted = false }
    }

    Rectangle {
        visible: root.scrolling
        x: root.origin.x - width / 2
        y: root.origin.y - height / 2
        width: 26; height: 26; radius: 13
        color: AppTheme.surfaceContainerLow
        border.color: AppTheme.outline
        Text {
            anchors.centerIn: parent
            text: "↕"
            color: AppTheme.colorOnSurface
            font.family: AppTheme.uiFont
            font.pixelSize: 18
        }
    }

    Timer {
        id: timer
        interval: 16; repeat: true
        onTriggered: {
            const now = Date.now()
            const elapsed = Math.min(0.05, (now - root.lastTick) / 1000)
            root.lastTick = now
            const distance = Math.max(0, Math.abs(root.displacement) - 12)
            const speed = Math.sign(root.displacement) * Math.min(1800, 700 * Math.pow(distance / 100, 1.6))
            const first = root.target.originY
            const last = first + Math.max(0, root.target.contentHeight - root.target.height)
            root.target.contentY = Math.max(first, Math.min(last, root.target.contentY + speed * elapsed))
        }
    }
}
