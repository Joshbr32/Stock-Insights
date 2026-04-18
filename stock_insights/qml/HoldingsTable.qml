import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

Card {
    id: root
    property var account: null
    padding: 16

    // Single source of truth for column layout. RowLayout (not Row) +
    // Layout.preferredWidth = weight × 1000 = proportional widths that
    // shrink together when the table narrows. All columns left-aligned.
    readonly property var cols: [
        { key: "instrument",    label: "Instrument",      weight: 1.6 },
        { key: "qtyText",       label: "Qty",             weight: 1.0 },
        { key: "avgCost",       label: "Avg Cost",        weight: 1.0 },
        { key: "mark",          label: "Mark",            weight: 1.0 },
        { key: "unrealizedPl",  label: "Unrealized P/L",  weight: 1.4 },
        { key: "marketValue",   label: "Market Value",    weight: 1.4 },
        { key: "weight",        label: "Weight",          weight: 0.7 },
    ]
    // Reserved strip at the right edge of every row so the scrollbar
    // overlay sits in this gap instead of on top of the last column.
    readonly property int scrollPad: 12

    SectionTitle {
        title: "Open Holdings"
        subtitle: account && account.summary
            ? "MV " + account.summary.marketValue +
              "   •   Cost " + account.summary.costBasis +
              "   •   Unrealized " + account.summary.unrealizedPl
            : ""
    }

    // ── Header row ──────────────────────────────────────────────────────────
    Rectangle {
        Layout.fillWidth: true
        Layout.preferredHeight: 28
        color: "transparent"

        RowLayout {
            anchors.fill: parent
            anchors.rightMargin: root.scrollPad
            spacing: 0

            Repeater {
                model: root.cols
                Label {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.preferredWidth: modelData.weight * 1000
                    Layout.minimumWidth: 30
                    text: modelData.label
                    color: app.theme.textMuted
                    font.pointSize: 9
                    font.weight: Font.DemiBold
                    horizontalAlignment: Text.AlignLeft
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: 8
                    rightPadding: 8
                    elide: Label.ElideRight
                }
            }
        }
    }

    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: app.theme.border }

    // ── Body ────────────────────────────────────────────────────────────────
    Rectangle {
        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.minimumHeight: 100
        color: "transparent"
        clip: true

        ListView {
            id: list
            anchors.fill: parent
            model: account ? account.holdings : null
            spacing: 1
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            delegate: Rectangle {
                id: row
                width: list.width                                  // full width — alt-row backgrounds extend to right edge
                height: 32
                color: index % 2 === 0 ? "transparent" : Qt.lighter(app.theme.cardAlt, 1.02)

                Rectangle {                                        // short-position tint overlay
                    visible: model.isShort
                    anchors.fill: parent
                    color: "#1e3a5f"
                    opacity: 0.18
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.rightMargin: root.scrollPad            // leave gap for scrollbar
                    spacing: 0

                    // Col 0 — Instrument
                    Label {
                        Layout.fillWidth: true; Layout.fillHeight: true
                        Layout.preferredWidth: 1600; Layout.minimumWidth: 30
                        text: model.instrument
                        color: app.theme.text
                        font.pointSize: 10; font.weight: Font.DemiBold
                        horizontalAlignment: Text.AlignLeft
                        verticalAlignment: Text.AlignVCenter
                        leftPadding: 8; rightPadding: 8
                        elide: Label.ElideRight
                    }
                    // Col 1 — Qty
                    Label {
                        Layout.fillWidth: true; Layout.fillHeight: true
                        Layout.preferredWidth: 1000; Layout.minimumWidth: 30
                        text: model.qtyText
                        color: app.theme.text; font.pointSize: 10
                        horizontalAlignment: Text.AlignLeft
                        verticalAlignment: Text.AlignVCenter
                        leftPadding: 8; rightPadding: 8
                        elide: Label.ElideRight
                    }
                    // Col 2 — Avg Cost
                    Label {
                        Layout.fillWidth: true; Layout.fillHeight: true
                        Layout.preferredWidth: 1000; Layout.minimumWidth: 30
                        text: model.avgCost
                        color: app.theme.text; font.pointSize: 10
                        horizontalAlignment: Text.AlignLeft
                        verticalAlignment: Text.AlignVCenter
                        leftPadding: 8; rightPadding: 8
                        elide: Label.ElideRight
                    }
                    // Col 3 — Mark
                    Label {
                        Layout.fillWidth: true; Layout.fillHeight: true
                        Layout.preferredWidth: 1000; Layout.minimumWidth: 30
                        text: model.mark
                        color: app.theme.text; font.pointSize: 10
                        horizontalAlignment: Text.AlignLeft
                        verticalAlignment: Text.AlignVCenter
                        leftPadding: 8; rightPadding: 8
                        elide: Label.ElideRight
                    }
                    // Col 4 — Unrealized P/L (sign-colored)
                    Label {
                        Layout.fillWidth: true; Layout.fillHeight: true
                        Layout.preferredWidth: 1400; Layout.minimumWidth: 30
                        text: model.unrealizedPl
                        color: model.unrealizedSign > 0 ? app.theme.good
                             : model.unrealizedSign < 0 ? app.theme.bad
                             : app.theme.text
                        font.pointSize: 10; font.weight: Font.DemiBold
                        horizontalAlignment: Text.AlignLeft
                        verticalAlignment: Text.AlignVCenter
                        leftPadding: 8; rightPadding: 8
                        elide: Label.ElideRight
                    }
                    // Col 5 — Market Value
                    Label {
                        Layout.fillWidth: true; Layout.fillHeight: true
                        Layout.preferredWidth: 1400; Layout.minimumWidth: 30
                        text: model.marketValue
                        color: app.theme.text; font.pointSize: 10
                        horizontalAlignment: Text.AlignLeft
                        verticalAlignment: Text.AlignVCenter
                        leftPadding: 8; rightPadding: 8
                        elide: Label.ElideRight
                    }
                    // Col 6 — Weight
                    Label {
                        Layout.fillWidth: true; Layout.fillHeight: true
                        Layout.preferredWidth: 700; Layout.minimumWidth: 30
                        text: model.weight
                        color: app.theme.textMuted; font.pointSize: 10
                        horizontalAlignment: Text.AlignLeft
                        verticalAlignment: Text.AlignVCenter
                        leftPadding: 8; rightPadding: 8
                        elide: Label.ElideRight
                    }
                }

                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.RightButton
                    onClicked: app.showHoldingsMenu(model.instrument)
                }
            }
        }

        // Empty state — only after first data load.
        Label {
            anchors.centerIn: parent
            visible: account && account.loaded && account.holdings.rowCount() === 0
            text: "No open positions"
            color: app.theme.textMuted
            font.pointSize: 10
        }
    }
}
