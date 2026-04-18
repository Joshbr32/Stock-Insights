import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

// One account's view: top row (goal | analytics), holdings card, trades card.
ColumnLayout {
    id: root
    property var account: null
    spacing: 12

    // Top row — goal dashboard takes ~2/3 of the width, analytics ~1/3.
    // The ratio is set via Layout.preferredWidth: when both children have
    // fillWidth and concrete preferredWidth values, the row distributes the
    // available width proportionally to those values (and shrinks each
    // proportionally if total preferred > parent width).
    RowLayout {
        Layout.fillWidth: true
        spacing: 12

        GoalDashboard {
            account: root.account
            Layout.fillWidth: true
            // Goal:Analytics ≈ 1.3:1 — Analytics is denser (13 metrics
            // vs. Goal's 10) so it gets a bigger share than the visual
            // would suggest. Lower minimum widths than the cards' "ideal"
            // because at narrow window sizes the cards must shrink (or
            // they'd push the whole right pane past the window edge).
            Layout.preferredWidth: 1300
            Layout.minimumWidth: 240
            Layout.alignment: Qt.AlignTop
        }

        AnalyticsPanel {
            account: root.account
            Layout.fillWidth: true
            Layout.preferredWidth: 1000
            Layout.minimumWidth: 220
            Layout.alignment: Qt.AlignTop
        }
    }

    HoldingsTable {
        account: root.account
        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.preferredHeight: 220
        Layout.minimumHeight: 120
    }

    TradesTable {
        account: root.account
        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.preferredHeight: 320
        Layout.minimumHeight: 160
    }
}
