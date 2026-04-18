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
        ComboBox {
            id: statusCombo
            Layout.preferredWidth: 130
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
        Layout.minimumHeight: 80
        color: "transparent"
        clip: true

        ListView {
            id: list
            anchors.fill: parent
            spacing: 1
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            model: account ? account.trades : null

            delegate: Rectangle {
                id: row
                width: list.width                       // full width — alt-row backgrounds fill the row
                height: 32
                color: index % 2 === 0 ? "transparent" : Qt.lighter(app.theme.cardAlt, 1.02)

                Rectangle {
                    visible: model.status === "WAITING"
                    anchors.fill: parent
                    color: "#a0700a"; opacity: 0.16
                }
                Rectangle {
                    visible: model.status === "SHORT" || model.status === "COVERED"
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
                        Layout.preferredWidth: 700; Layout.minimumWidth: 30
                        text: model.shareCount
                        color: app.theme.text; font.pointSize: 10
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
                        color: app.theme.textMuted; font.pointSize: 9
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
                        color: app.theme.text; font.pointSize: 10
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
                        color: app.theme.text; font.pointSize: 10
                        horizontalAlignment: Text.AlignLeft
                        verticalAlignment: Text.AlignVCenter
                        leftPadding: 8; rightPadding: 8
                        elide: Label.ElideRight
                    }
                    // Col 5 — Profit (sign-colored)
                    Label {
                        Layout.fillWidth: true; Layout.fillHeight: true
                        Layout.preferredWidth: 1200; Layout.minimumWidth: 30
                        text: model.tradeProfit
                        color: model.profitSign > 0 ? app.theme.good
                             : model.profitSign < 0 ? app.theme.bad
                             : app.theme.text
                        font.pointSize: 10; font.weight: Font.DemiBold
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
                        color: app.theme.text; font.pointSize: 10
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
                        color: app.theme.text; font.pointSize: 10
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
                        color: app.theme.textMuted; font.pointSize: 10
                        horizontalAlignment: Text.AlignLeft
                        verticalAlignment: Text.AlignVCenter
                        leftPadding: 8; rightPadding: 8
                        elide: Label.ElideRight
                    }
                }

                MouseArea {
                    anchors.fill: parent
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
            font.pointSize: 10
        }
    }

    // Edit / Delete are accessible via the right-click context menu on any
    // trade row, plus double-click to edit. The dedicated action-buttons
    // row was redundant and pushed the card content past the visible
    // bottom edge at smaller window heights.
}
