import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "."

// Root scene mounted in MainWindow's QQuickWidget. `app` (AppController)
// is injected from Python via setContextProperty().
//
// The root is a Control so the resolved UI font family, base size and
// tabular figures propagate to every Label/Control in the scene; children
// only override size and weight.
Control {
    id: root
    padding: 12
    font.family: app.theme.fontFamily
    font.pixelSize: 13 * app.theme.fontScale
    font.features: { "tnum": 1 }

    background: Rectangle { color: app.theme.bg }

    contentItem: SplitView {
        id: split
        orientation: Qt.Horizontal

        // 12 px gutter between watchlist and portfolio; a hairline appears
        // only while hovering / dragging so the resize affordance is findable.
        handle: Item {
            implicitWidth: 12
            Rectangle {
                anchors.centerIn: parent
                width: 2
                height: parent.height
                radius: 1
                color: SplitHandle.pressed ? app.theme.primary
                     : SplitHandle.hovered ? app.theme.border
                     : "transparent"
            }
        }

        WatchlistPane {
            SplitView.preferredWidth: 240
            SplitView.minimumWidth: 190
            SplitView.maximumWidth: 380
        }

        PortfolioPane {
            SplitView.fillWidth: true
            SplitView.minimumWidth: 480
        }
    }
}
