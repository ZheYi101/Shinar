pragma Singleton
import QtQuick

QtObject {
    readonly property bool dark: learningViewModel.preferences.themeMode === "dark" || (learningViewModel.preferences.themeMode === "system" && learningViewModel.systemDark)
    readonly property bool reducedMotion: learningViewModel.preferences.reducedMotion
    readonly property int duration: reducedMotion ? 0 : 180
    readonly property int motionFast: reducedMotion ? 0 : 110
    readonly property color primary: dark ? "#B8C8AA" : "#56634F"
    readonly property color colorOnPrimary: dark ? "#23301E" : "#FAF7EF"
    readonly property color primaryContainer: dark ? "#34412F" : "#E1E4D7"
    readonly property color colorOnPrimaryContainer: dark ? "#E0E8D8" : "#35412F"
    readonly property color secondaryContainer: dark ? "#373B32" : "#E8E3D7"
    readonly property color colorOnSecondaryContainer: dark ? "#E0E2D7" : "#3F382F"
    readonly property color surface: dark ? "#1B1D19" : "#F7F3E9"
    readonly property color surfaceContainerLow: dark ? "#22251F" : "#EEE8DC"
    readonly property color surfaceContainer: dark ? "#292C25" : "#EFEADE"
    readonly property color surfaceContainerHigh: dark ? "#34382F" : "#E8E1D4"
    readonly property color colorOnSurface: dark ? "#E5E5DC" : "#3F382F"
    readonly property color colorOnSurfaceVariant: dark ? "#B5B9AA" : "#6B6257"
    readonly property color outline: dark ? "#89907F" : "#887A67"
    readonly property color outlineVariant: dark ? "#41463B" : "#D9CEBD"
    readonly property color error: dark ? "#F2B8B5" : "#B3261E"
    readonly property color errorContainer: dark ? "#8C1D18" : "#F9DEDC"
    readonly property color colorOnErrorContainer: dark ? "#F9DEDC" : "#410E0B"
    readonly property color scrim: "#66000000"
    readonly property int space: 4
    readonly property int gapSmall: 8
    readonly property int gapMedium: 12
    readonly property int gapLarge: 16
    readonly property int sectionGap: 20
    readonly property int pageMargin: 24
    readonly property int compactPageMargin: 16
    readonly property int railWidth: 208
    readonly property int contextWidth: 320
    readonly property int topBarHeight: 36
    readonly property int navigationBarHeight: 80
    readonly property int touchTarget: 36
    readonly property int compactBreakpoint: 600
    readonly property int expandedBreakpoint: 1200
    readonly property real bodyLineHeight: 1.35
    readonly property int cardRadius: 5
    readonly property int panelRadius: 6
    readonly property int dialogRadius: 8
    readonly property int bodyLarge: 16
    readonly property int bodyMedium: 14
    readonly property int labelLarge: 14
    readonly property int titleLarge: 22
    readonly property int headlineMedium: 28
    readonly property string uiFont: Qt.platform.os === "windows" ? "Microsoft YaHei UI" : Qt.platform.os === "osx" ? "PingFang SC" : "Noto Sans CJK SC"
    readonly property string readingFont: "Noto Serif SC"
    readonly property string japaneseReadingFont: "Noto Serif JP"
    readonly property string japaneseFont: Qt.platform.os === "windows" ? "Yu Gothic UI" : uiFont
}
