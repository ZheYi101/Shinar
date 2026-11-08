import QtQuick
import QtWebEngine
import QtWebChannel
import "../design"

WebEngineView {
    id: surface
    objectName: "foliateReader"
    property string documentIdentity: workspace.readerId
    property bool bookReady: false
    clip: true
    property int readingSize: width < 600 ? 18 : 20
    profile: readerRuntime.profile
    webChannel: WebChannel { id: sourceChannel }
    webChannelWorld: 0
    Component.onCompleted: {
        sourceChannel.registerObject("reader", readerRuntime.bridge)
        url = readerRuntime.url.toString() + "?document=" + documentIdentity
    }
    backgroundColor: AppTheme.surface
    settings.localContentCanAccessRemoteUrls: false
    settings.localContentCanAccessFileUrls: true
    settings.javascriptCanOpenWindows: false
    settings.javascriptCanAccessClipboard: false
    settings.pluginsEnabled: false
    settings.pdfViewerEnabled: false
    function appearance() {
        runJavaScript("window.shinarReader?.setAppearance(" + JSON.stringify({
            dark: AppTheme.dark, background: AppTheme.surface.toString(),
            ink: AppTheme.colorOnSurface.toString(), primary: AppTheme.primary.toString(), size: readingSize
        }) + ")")
    }
    onReadingSizeChanged: appearance()
    onLoadingChanged: function(request) {
        if (request.status === WebEngineView.LoadFailedStatus) workspace.readerFailed(documentIdentity)
    }
    onNavigationRequested: function(request) {
        const target = request.url.toString()
        const expected = readerRuntime.url.toString() + "?document=" + documentIdentity
        if (!target.startsWith("blob:") && target !== expected) request.action = WebEngineNavigationRequest.IgnoreRequest
    }
    Connections {
        target: readerRuntime.bridge
        function onLoaded(identity) { if (identity === surface.documentIdentity) { surface.bookReady = true; surface.appearance() } }
    }
    Connections {
        target: workspace
        function onReaderSelectionRequested(identity, start, end) {
            if (identity === surface.documentIdentity) surface.runJavaScript("window.shinarReader?.showSelection(" + start + "," + end + ")")
        }
        function onChanged() { surface.runJavaScript("window.shinarReader?.setBoundary(" + (workspace.route === "scope" ? workspace.pendingEnd : -1) + ")") }
    }
    Connections { target: AppTheme; function onDarkChanged() { surface.appearance() } }
    Timer { interval: 15000; running: !surface.bookReady; onTriggered: workspace.readerFailed(surface.documentIdentity) }
}
