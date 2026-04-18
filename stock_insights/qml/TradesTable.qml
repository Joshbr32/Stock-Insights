import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

Card {
    id: root
    property var account: null
    padding: 16

    // Single source of truth for column layout. RowLayout enforces children
    // fit within the parent — no horizontal overflow even at very narrow
    // window widths. All columns are left-aligned to keep cell text
    // visually grouped on the left side of the column.
    readonly property var cols: [
        { key: "instrument",  label: "Instrument", weight: 1.5 },
        { key: "shareCount",  label: "Qty",        weight: 0.7 },
        { key: "status",      label: "Status",     weight: 0.9 },
        { key: "buyPrice",    label: "Buy",        weight: 1.0 },
        { key: "sellPrice",   label: "Sell",       weight: 1.0 },
        { key: "tradeProfit", label: "Profit",     weight: 1.2 },
        { key: "openDate",    label: "Open",       weight: 1.0 },
        { key: "closeDate",   label: "Close",      weight: 1.0 },
        { key: "daysToClose", label: "Days",       weight: 0.6 },
    ]
    // Reserved strip at the right edge of each row so the scrollbar
    // overlay sits in this gap rather than over the rightmost column.
    readonly property int scrollPad: 12

    SectionTitle {
        title: "Trade History"
        subtitle: account && account.loaded
            ? (account.totalTradeCount + (account.totalTradeCount === 1 ? " trade" : " trades"))
            : ""
    }

    // ── Filter row ──────────────────────────────────────────────────────────
    RowLayout {
        Layout.fillWidth: true
        spacing: 8

        TextField {
            id: filterField
            Layout.fillWidth: true
            placeholderText: "Filter by instrument, status, notes…"
            placeholderTextColor: app.theme.textMuted
            color: app.theme.text
            selectByMouse: true
            text: account ? account.textFilter : ""
            onTextEdited: if (account) account.setTextFilter(text)
            background: Rectangle {
                radius: 8
                color: app.theme.card
                border.color: filterField.activeFocus ? app.theme.secondary : app.theme.border
                border.width: 1
            }
        }
        ThemedComboBox {
            id: statusCombo
            Layout.preferredWidth: 150
            model: ["All statuses", "WAITING", "OPEN", "SHORT", "CLOSED", "COVERED"]
            currentIndex: {
                if (!account) return 0
                var s = account.statusFilter
                if (!s) return 0
                var i = model.indexOf(s)
                return i >= 0 ? i : 0
            }
            onActivated: function(index) {
                if (!account) return
                account.setStatusFilter(index === 0 ? "" : model[index])
            }
        }
        ToolButton2 {
            text: "+ Trade"
            primary: true
            onClicked: app.addTrade()
        }
    }

    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: app.theme.border }

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
                    font.pointSize: 9 * app.theme.fontScale
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
        // 3 trade rows × 32 px + a couple px of breathing room ≈ 100.
        // Below this the body clips partial rows — scrollbar reveals the rest.
        Layout.minimumHeight: 100
        color: "transparent"
        clip: true

        ListView {
            id: list
            anchors.fill: parent
            spacing: 1
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ThemedScrollBar { }
            model: account ? account.trades : null

            delegate: Rectangle {
                id: row
                width: list.width                       // full width — alt-row backgrounds fill the row
                height: 32
                radius: 4

                // Shared row-state model (see WatchlistPane / HoldingsTable).
                //   selected → filled with app.theme.primary
                //   hovered  → 1.5 px primary outline around the normal base
                //   odd row  → subtle zebra stripe
                //   even row → transparent (card bg shows through)
                property bool selected: list.currentIndex === index
                property bool hovered:  rowMouse.containsMouse

                color: row.selected
                    ? app.theme.primary
                    : (index % 2 === 0 ? "transparent"
                                       : Qt.lighter(app.theme.cardAlt, 1.02))
                border.color: row.hovered && !row.selected
                    ? app.theme.primary : "transparent"
                border.width: 1.5

                Behavior on color        { ColorAnimation { duration: 100 } }
                Behavior on border.color { ColorAnimation { duration: 100 } }

                // Status tints are hidden when the row is selected — on a
                // primary-filled row they'd conflict with the selection
                // color; the Status column text + color of the fill still
                // convey "this row is selected and waiting/short".
                Rectangle {
                    visible: model.status === "WAITING" && !row.selected
                    anchors.fill: parent
                    color: "#a0700a"; opacity: 0.16
                }
                Rectangle {
                    visible: (model.status === "SHORT" || model.status === "COVERED") && !row.selected
                    anchors.fill: parent
                    color: "#1e3a5f"; opacity: 0.18
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.rightMargin: root.scrollPad   // scrollbar gap
                    spacing: 0

                    // Col 0 — Instrument
                    Label {
                        Layout.fillWidth: true; Layout.fillHeight: true
                        Layout.preferredWidth: 1500; Layout.minimumWidth: 30
                        text: model.instrument
                        // When the row is filled with `primary`, switch
                        // text to textOnColor so it stays readable.
                        color: row.selected ? app.theme.textOnColor : app.theme.text
                        font.pointSize: 10 * app.theme.fontScale; font.weight: Font.DemiBold
                        horizontalAlignment: Text.AlignLeft
                        verticalAlignment: Text.AlignVCenter
                        leftPadding: 8; rightPadding: 8
                        elide: Label.ElideRight
                    }
                    // Col 1 — Qty
                    Label {
                        Layout.fillWidth: true; Layout.fillHeight: true
                        Layout.preferredWidth: 700; Layout.minimumWidth: 30
                        text: model.shareCount
                        color: row.selected ? app.theme.textOnColor : app.theme.text
                        font.pointSize: 10 * app.theme.fontScale
                        horizontalAlignment: Text.AlignLeft
                        verticalAlignment: Text.AlignVCenter
                        leftPadding: 8; rightPadding: 8
                        elide: Label.ElideRight
                    }
                    // Col 2 — Status
                    Label {
                        Layout.fillWidth: true; Layout.fillHeight: true
                        Layout.preferredWidth: 900; Layout.minimumWidth: 30
                        text: model.status
                        color: row.selected ? app.theme.textOnColor : app.theme.textMuted
                        font.pointSize: 9 * app.theme.fontScale
                        horizontalAlignment: Text.AlignLeft
                        verticalAlignment: Text.AlignVCenter
                        leftPadding: 8; rightPadding: 8
                        elide: Label.ElideRight
                    }
                    // Col 3 — Buy
                    Label {
                        Layout.fillWidth: true; Layout.fillHeight: true
                        Layout.preferredWidth: 1000; Layout.minimumWidth: 30
                        text: model.buyPrice
                        color: row.selected ? app.theme.textOnColor : app.theme.text
                        font.pointSize: 10 * app.theme.fontScale
                        horizontalAlignment: Text.AlignLeft
                        verticalAlignment: Text.AlignVCenter
                        leftPadding: 8; rightPadding: 8
                        elide: Label.ElideRight
                    }
                    // Col 4 — Sell
                    Label {
                        Layout.fillWidth: true; Layout.fillHeight: true
                        Layout.preferredWidth: 1000; Layout.minimumWidth: 30
                        text: model.sellPrice
                        color: row.selected ? app.theme.textOnColor : app.theme.text
                        font.pointSize: 10 * app.theme.fontScale
                        horizontalAlignment: Text.AlignLeft
                        verticalAlignment: Text.AlignVCenter
                        leftPadding: 8; rightPadding: 8
                        elide: Label.ElideRight
                    }
                    // Col 5 — Profit (sign-colored, with selected override)
                    Label {
                        Layout.fillWidth: true; Layout.fillHeight: true
                        Layout.preferredWidth: 1200; Layout.minimumWidth: 30
                        text: model.tradeProfit
                        color: row.selected
                            ? app.theme.textOnColor
                            : (model.profitSign > 0 ? app.theme.good
                               : model.profitSign < 0 ? app.theme.bad
                               : app.theme.text)
                        font.pointSize: 10 * app.theme.fontScale; font.weight: Font.DemiBold
                        horizontalAlignment: Text.AlignLeft
                        verticalAlignment: Text.AlignVCenter
                        leftPadding: 8; rightPadding: 8
                        elide: Label.ElideRight
                    }
                    // Col 6 — Open
                    Label {
                        Layout.fillWidth: true; Layout.fillHeight: true
                        Layout.preferredWidth: 1000; Layout.minimumWidth: 30
                        text: model.openDate
                        color: row.selected ? app.theme.textOnColor : app.theme.text
                        font.pointSize: 10 * app.theme.fontScale
                        horizontalAlignment: Text.AlignLeft
                        verticalAlignment: Text.AlignVCenter
                        leftPadding: 8; rightPadding: 8
                        elide: Label.ElideRight
                    }
                    // Col 7 — Close
                    Label {
                        Layout.fillWidth: true; Layout.fillHeight: true
                        Layout.preferredWidth: 1000; Layout.minimumWidth: 30
                        text: model.closeDate
                        color: row.selected ? app.theme.textOnColor : app.theme.text
                        font.pointSize: 10 * app.theme.fontScale
                        horizontalAlignment: Text.AlignLeft
                        verticalAlignment: Text.AlignVCenter
                        leftPadding: 8; rightPadding: 8
                        elide: Label.ElideRight
                    }
                    // Col 8 — Days
                    Label {
                        Layout.fillWidth: true; Layout.fillHeight: true
                        Layout.preferredWidth: 600; Layout.minimumWidth: 30
                        text: model.daysToClose
                        color: row.selected ? app.theme.textOnColor : app.theme.textMuted
                        font.pointSize: 10 * app.theme.fontScale
                        horizontalAlignment: Text.AlignLeft
                        verticalAlignment: Text.AlignVCenter
                        leftPadding: 8; rightPadding: 8
                        elide: Label.ElideRight
                    }
                }

                MouseArea {
                    id: rowMouse
                    anchors.fill: parent
                    hoverEnabled: true              // drives the row's hover-highlight color
                    cursorShape: Qt.PointingHandCursor
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    onDoubleClicked: app.editTrade(model.sourceIndex)
                    onClicked: function (mouse) {
                        list.currentIndex = index
                        if (mouse.button === Qt.RightButton) {
                            app.showTradeMenu(model.sourceIndex)
                        }
                    }
                }
            }
        }

        // Empty state — only after first data load.
        Label {
            anchors.centerIn: parent
            visible: account && account.loaded && account.trades.rowCount() === 0
            text: account && (account.textFilter.length > 0 || account.statusFilter.length > 0)
                ? "No trades match the current filter"
                : "No trades yet — click + Trade to add one"
            color: app.theme.textMuted
            font.pointSize: 10 * app.theme.fontScale
        }
    }

    // Edit / Delete are accessible via the right-click context menu on any
    // trade row, plus double-click to edit. The dedicated action-buttons
    // row was redundant and pushed the card content past the visible
    // bottom edge at smaller window heights.
}
