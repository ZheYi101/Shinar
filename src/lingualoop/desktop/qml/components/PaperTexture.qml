import QtQuick
import "../design"

Image {
    property bool quiet: false
    source: Qt.resolvedUrl("../assets/decorative/paper-fibers.svg")
    fillMode: Image.Tile
    horizontalAlignment: Image.AlignLeft
    verticalAlignment: Image.AlignTop
    opacity: (AppTheme.dark ? 0.08 : 0.24) * (quiet ? 0.45 : 1)
    Accessible.ignored: true
}
