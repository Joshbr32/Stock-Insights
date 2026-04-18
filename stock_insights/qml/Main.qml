import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

// Root scene mounted inside the QQuickWidget central widget of MainWindow.
// `app` is injected from Python via setContextProperty().
Rectangle {
    id: root
    color: app.theme.bg

    SplitView {
        id: split
        anchors.fill: parent
        anchors.margins: 10
        orientation: Qt.Horizontal

        handle: Rectangle {
            implicitWidth: 8
            color: SplitHandle.pressed ? app.theme.secondary
                 : SplitHandle.hovered ? Qt.lighter(app.theme.border, 1.4)
                 : "transparent"
            radius: 3
            Behavior on color { ColorAnimation { duration: 100 } }
        }

        // Left: watchlist
        WatchlistPane {
            SplitView.preferredWidth: 260
            SplitView.minimumWidth: 200
            SplitView.maximumWidth: 420
        }

        // Right: portfolio tabs + content. Keep the SplitView min low
        // enough that the right pane never has to push past the viewport
        // edge — the inner cards handle their own intelligent shrinking.
        PortfolioPane {
            SplitView.fillWidth: true
            SplitView.minimumWidth: 420
        }
    }
}
