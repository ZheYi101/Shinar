import QtQuick

Item {
    id: handles
    visible: !desktopWindow.maximized
    // Qt forwards the native operation, retaining OS pointer capture and DPI scaling.
    Repeater {
        model: [
            {name: "top", edges: Qt.TopEdge, px: 6, py: 0, pw: handles.width - 12, ph: 6, cursor: Qt.SizeVerCursor},
            {name: "bottom", edges: Qt.BottomEdge, px: 6, py: handles.height - 6, pw: handles.width - 12, ph: 6, cursor: Qt.SizeVerCursor},
            {name: "left", edges: Qt.LeftEdge, px: 0, py: 6, pw: 6, ph: handles.height - 12, cursor: Qt.SizeHorCursor},
            {name: "right", edges: Qt.RightEdge, px: handles.width - 6, py: 6, pw: 6, ph: handles.height - 12, cursor: Qt.SizeHorCursor},
            {name: "topLeft", edges: Qt.TopEdge | Qt.LeftEdge, px: 0, py: 0, pw: 6, ph: 6, cursor: Qt.SizeFDiagCursor},
            {name: "topRight", edges: Qt.TopEdge | Qt.RightEdge, px: handles.width - 6, py: 0, pw: 6, ph: 6, cursor: Qt.SizeBDiagCursor},
            {name: "bottomLeft", edges: Qt.BottomEdge | Qt.LeftEdge, px: 0, py: handles.height - 6, pw: 6, ph: 6, cursor: Qt.SizeBDiagCursor},
            {name: "bottomRight", edges: Qt.BottomEdge | Qt.RightEdge, px: handles.width - 6, py: handles.height - 6, pw: 6, ph: 6, cursor: Qt.SizeFDiagCursor}
        ]
        MouseArea {
            required property var modelData
            objectName: "resize_" + modelData.name
            x: modelData.px; y: modelData.py; width: modelData.pw; height: modelData.ph
            cursorShape: modelData.cursor
            acceptedButtons: Qt.LeftButton
            onPressed: desktopWindow.startResize(modelData.edges)
        }
    }
}
