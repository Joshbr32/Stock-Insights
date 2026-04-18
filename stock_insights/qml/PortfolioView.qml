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

        // Layout.alignment: Qt.AlignTop is intentionally absent — without
        // an alignment hint, RowLayout stretches both cards to the tallest
        // implicit height (see RowLayout docs: "By default, items have
        // their preferred size in the direction of the layout, but
        // stretch perpendicular to it"). This keeps the two cards
        // visually balanced at equal heights across every window size.
        GoalDashboard {
            account: root.account
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredWidth: 1300
            Layout.minimumWidth: 240
            // Split hero (44) + progress bar (6) + pills (30) + separator
            // + 2×5 metrics grid (~100) + section title + spacings +
            // padding = ~260. Below this the content overlaps/clips.
            Layout.minimumHeight: 260
        }

        AnalyticsPanel {
            account: root.account
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredWidth: 1000
            Layout.minimumWidth: 220
            // Section title + separator + 2×6 metrics (~120) + Est. Yearly
            // featured row (52) + spacings + padding ≈ 240.
            Layout.minimumHeight: 240
        }
    }

    // Holdings / Trades min heights: enough vertical space for the card
    // chrome (section title, header, separator, action row, padding) PLUS
    // at least 3 visible rows (≈ 96 px) so the user always sees real data
    // at the minimum window size — per the "3 entries minimum" spec.
    HoldingsTable {
        account: root.account
        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.preferredHeight: 220
        Layout.minimumHeight: 200
    }

    TradesTable {
        account: root.account
        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.preferredHeight: 320
        Layout.minimumHeight: 260
    }
}
