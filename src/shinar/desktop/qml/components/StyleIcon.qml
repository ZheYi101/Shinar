import QtQuick

Image {
    property string name: "book"
    source: "../assets/illustrated/" + name + ".png"
    fillMode: Image.PreserveAspectFit
    sourceClipRect: name === "book" ? Qt.rect(207,329,840,616) : name === "mic" ? Qt.rect(400,262,454,769) : Qt.rect(142,204,971,845)
    width: 24
    height: 24
    smooth: true
    Accessible.ignored: true
}
