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

    // Equity curve sits between the summary metrics above and the
    // tables below — it tells the "running cumulative P/L" story that
    // ties the analytics numbers to the per-trade list. minimumHeight
    // accounts for: Card padding (32) + SectionTitle (~22) + divider
    // (1) + 2× spacing (20) + chart wrapper min (120) = ~195. Round up
    // to 210 for headroom at larger font scales.
    EquityCurveCard {
        account: root.account
        // Toggled by View menu → "Hide Equity Curve". QtQuick.Layouts
        // skips invisible children from sizing entirely (Layout doc:
        // "items with visible: false are excluded from the layout"),
        // so the surrounding cards expand to reclaim this slot
        // automatically when the user hides the curve.
        visible: app.equityCurveVisible
        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.preferredHeight: 220
        Layout.minimumHeight: 210
    }

    // Holdings / Trades min heights cover the card chrome (section
    // title, header, separator, padding) PLUS at least 3 visible rows
    // (≈ 96 px) so the user always sees real data at the minimum window
    // size — per the "3 entries minimum" spec.
    //
    // Holdings stack at min: padding (32) + SectionTitle (~22) + header
    // (28) + divider (1) + body (100) + 3× spacing (30) = ~213.
    HoldingsTable {
        account: root.account
        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.preferredHeight: 240
        Layout.minimumHeight: 220
    }

    // Trades stack at min: padding (32) + SectionTitle (~22) + filter
    // row (~30) + 2× divider (2) + header (28) + body (100) + 5×
    // spacing (50) = ~264. Bumped to 300 so a couple extra rows are
    // visible — Trade History is the card the user looks at most.
    TradesTable {
        account: root.account
        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.preferredHeight: 340
        Layout.minimumHeight: 300
    }
}
