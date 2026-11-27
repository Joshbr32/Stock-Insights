import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "."

// One account's page, ordered by the questions the user opens the app for:
//   1. Am I on pace?          -> GoalDashboard (pace rail)
//   2. What is open now?      -> HoldingsTable
//   3. How am I trading?      -> EquityCurveCard | AnalyticsPanel
//   4. What did I do?         -> TradesTable (takes the remaining height)
//
// The page scrolls instead of clipping: every card keeps its natural
// height, and when the window is taller than the content the trades table
// grows to fill it. So no minimum window height is needed for correctness.
Flickable {
    id: root
    property var account: null

    readonly property bool scrollable: page.implicitHeight > height + 1
    clip: true
    contentWidth: width
    contentHeight: page.height
    boundsBehavior: Flickable.StopAtBounds
    ScrollBar.vertical: ThemedScrollBar { }

    ColumnLayout {
        id: page
        // Leave a gutter for the page scrollbar only when it is needed.
        width: root.width - (root.scrollable ? 14 : 0)
        height: Math.max(implicitHeight, root.height)
        spacing: 12

        GoalDashboard {
            account: root.account
            Layout.fillWidth: true
        }

        HoldingsTable {
            account: root.account
            Layout.fillWidth: true
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: false
            spacing: 12

            // Hidden via View > Hide equity curve; layouts skip invisible
            // items, so the analytics panel then takes the full row.
            EquityCurveCard {
                account: root.account
                visible: app.equityCurveVisible
                Layout.fillWidth: true
                Layout.minimumWidth: 260
                // Same height as the analytics list beside it; only the
                // trades table absorbs spare page height.
                Layout.preferredHeight: analytics.implicitHeight
            }

            AnalyticsPanel {
                id: analytics
                account: root.account
                Layout.fillWidth: !app.equityCurveVisible
                // 390 = the header row (title + tag + range combos + padding);
                // narrower and the combos push the values past the card edge.
                Layout.minimumWidth: 390
                Layout.preferredWidth: app.equityCurveVisible ? Math.max(390, Math.min(440, root.width * 0.36)) : -1
                Layout.alignment: Qt.AlignTop
            }
        }

        TradesTable {
            account: root.account
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 420
            Layout.preferredHeight: 420
        }
    }
}
