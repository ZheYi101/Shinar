import QtQuick

Item {
    id: control
    property url iconSource
    property color tint: "#3F382F"
    width: 24; height: 24
    function crop(url) {
        const name = url.toString().split("/").pop().split(".")[0]
        const bounds = {book:[207,329,840,616],chat:[142,276,971,736],mic:[400,262,454,769],settings:[279,285,696,713],review:[357,311,542,636],audio:[194,204,867,845]}
        const b = bounds[name]
        return url.toString().indexOf(".png") >= 0 && b ? Qt.rect(b[0],b[1],b[2],b[3]) : Qt.rect(0,0,0,0)
    }
    Image { anchors.fill: parent; source: control.iconSource; sourceClipRect: control.crop(source); fillMode: Image.PreserveAspectFit; smooth: true; opacity: control.enabled ? 1 : 0.5 }
}
