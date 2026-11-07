import QtQuick
import "../design"

Image {
    property string motif: "botanical-stamp"
    source: Qt.resolvedUrl("../assets/decorative/" + motif + (motif === "cloth-book" ? ".png" : ".svg"))
    fillMode: Image.PreserveAspectFit
    opacity: motif === "cloth-book" ? (AppTheme.dark ? 0.60 : 0.86) : (AppTheme.dark ? 0.32 : 0.60)
    smooth: true
    Accessible.ignored: true
}
