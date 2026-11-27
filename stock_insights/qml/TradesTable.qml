import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "."

// Trade history for the selected date range (set in Performance).
// Double-click or Enter edits; right-click or the Menu key opens the trade
// menu; Delete asks to delete. Search + status narrow the list in place.
Card {
    id: root
    property var account: null
    readonly property int rowH: 32

    readonly property var cols: [
        { key: "instrument",  label: "Symbol",  w: 1.1 },
        { key: "statusText",  label: "Status",  w: 0.9 },
        { key: "shareCount",  label: "Shares",  w: 0.7, right: true },
        { key: "buyPrice",    label: "Entry",   w: 1.0, right: true },
        { key: "sellPrice",   label: "Exit",    w: 1.0, right: true },
        { key: "tradeProfit", label: "Profit",  w: 1.1, right: true, pl: true },
        { key: "returnText",  label: "Return",  w: 0.9, right: true, pl: true },
        { key: "openDate",    label: "Opened",  w: 1.0, right: true },
        { key: "closeDate",   label: "Closed",  w: 1.0, right: true },
        { key: "daysToClose", label: "Days",    w: 0.6, right: true }
    ]
    // Display label -> TradesModel status code (the filter matches codes).
    readonly property var statusLabels: ["All statuses", "Pending", "Open", "Short", "Closed", "Covered"]
    readonly property var statusCodes: ["", "WAITING", "OPEN", "SHORT", "CLOSED", "COVERED"]
    readonly property bool filtered: account && (account.textFilter.length > 0 || account.statusFilter.length > 0)

    function _rangeLabel(key) {
        if (key === "week")  return "this week"
        if (key === "month") return "this month"
        if (key === "30d")   return "last 30 days"
        if (key === "ytd")   return "year to date"
        return "all time"
    }

    SectionTitle {
        title: "Trade history"
        subtitle: account && account.loaded
            ? (account.totalTradeCount === 1 ? "1 trade, " : account.totalTradeCount + " trades, ")
              + _rangeLabel(account.dateRangeKey || "all")
            : ""
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: 8

        TextField {
            id: filterField
            Layout.fillWidth: true
            implicitHeight: 32
            leftPadding: 10
            placeholderText: "Search symbol, status or notes"
            placeholderTextColor: app.theme.textMuted
            color: app.theme.text
            font.pixelSize: 13 * app.theme.fontScale
            selectByMouse: true
            selectionColor: app.theme.primary
            selectedTextColor: app.theme.textOnColor
            text: account ? account.textFilter : ""
            onTextEdited: if (account) account.setTextFilter(text)
            Keys.onEscapePressed: if (account) { text = ""; account.setTextFilter("") }
            Accessible.name: "Search trades"
            background: Rectangle {
                radius: 6
                color: app.theme.cardAlt
                border.width: filterField.activeFocus ? 2 : 1
                border.color: filterField.activeFocus ? app.theme.primary : app.theme.border
            }
        }
        ThemedComboBox {
            id: statusCombo
            Layout.preferredWidth: 140
            model: root.statusLabels
            currentIndex: {
                if (!account || !account.statusFilter) return 0
                var i = root.statusCodes.indexOf(account.statusFilter)
                return i >= 0 ? i : 0
            }
            onActivated: function (index) {
                if (account) account.setStatusFilter(root.statusCodes[index])
            }
            Accessible.name: "Status filter"
        }
    }

    ColumnLayout {
        Layout.fillWidth: true
        Layout.fillHeight: true
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: root.rowH
            color: app.theme.cardAlt
            radius: 6

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 4
                anchors.rightMargin: 4 + 10
                spacing: 0
                Repeater {
                    model: root.cols
                    Label {
                        Layout.fillWidth: true
                        Layout.preferredWidth: modelData.w * 1000
                        Layout.minimumWidth: 24
                        text: modelData.label
                        color: app.theme.textMuted
                        font.pixelSize: 12 * app.theme.fontScale
                        font.weight: Font.DemiBold
                        horizontalAlignment: modelData.right ? Text.AlignRight : Text.AlignLeft
                        leftPadding: 8
                        rightPadding: 8
                        elide: Label.ElideRight
                    }
                }
            }
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: root.rowH * 3

            ListView {
                id: list
                anchors.fill: parent
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                currentIndex: -1
                activeFocusOnTab: true
                keyNavigationEnabled: true
                ScrollBar.vertical: ThemedScrollBar { }
                model: account ? account.trades : null
                Accessible.role: Accessible.Table
                Accessible.name: "Trade history"

                Keys.onReturnPressed: if (currentItem) app.editTrade(currentItem.sourceIndex)
                Keys.onEnterPressed: if (currentItem) app.editTrade(currentItem.sourceIndex)
                Keys.onMenuPressed: if (currentItem) app.showTradeMenu(currentItem.sourceIndex)
                Keys.onDeletePressed: if (currentItem) app.deleteTrade(currentItem.sourceIndex)

                delegate: Rectangle {
                    id: row
                    readonly property int sourceIndex: model.sourceIndex
                    readonly property var rowModel: model
                    readonly property bool selected: ListView.isCurrentItem
                    width: ListView.view.width
                    height: root.rowH
                    color: selected || mouse.containsMouse ? app.theme.cardAlt : "transparent"

                    // Selected row: 2 px primary bar on the left edge, so the
                    // selection reads without tinting the P/L colours.
                    Rectangle {
                        visible: row.selected
                        width: 2
                        height: parent.height - 8
                        anchors.verticalCenter: parent.verticalCenter
                        radius: 1
                        color: app.theme.primary
                    }
                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        height: 1
                        color: app.theme.border
                    }

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 4
                        anchors.rightMargin: 4 + 10
                        spacing: 0
                        Repeater {
                            model: root.cols
                            Label {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                Layout.preferredWidth: modelData.w * 1000
                                Layout.minimumWidth: 24
                                text: row.rowModel[modelData.key]
                                color: modelData.pl
                                    ? (row.rowModel.profitSign > 0 ? app.theme.good
                                       : row.rowModel.profitSign < 0 ? app.theme.bad : app.theme.textMuted)
                                    : (modelData.key === "statusText" || modelData.key === "daysToClose"
                                       || text === "—") ? app.theme.textMuted : app.theme.text
                                font.pixelSize: 13 * app.theme.fontScale
                                font.weight: modelData.key === "instrument" || modelData.key === "tradeProfit"
                                             ? Font.DemiBold : Font.Normal
                                font.italic: modelData.key === "statusText" && row.rowModel.isPending
                                horizontalAlignment: modelData.right ? Text.AlignRight : Text.AlignLeft
                                verticalAlignment: Text.AlignVCenter
                                leftPadding: 8
                                rightPadding: 8
                                elide: Label.ElideRight
                            }
                        }
                    }

                    MouseArea {
                        id: mouse
                        anchors.fill: parent
                        hoverEnabled: true
                        acceptedButtons: Qt.LeftButton | Qt.RightButton
                        onDoubleClicked: app.editTrade(model.sourceIndex)
                        onClicked: function (mouse) {
                            list.currentIndex = index
                            list.forceActiveFocus()
                            if (mouse.button === Qt.RightButton) app.showTradeMenu(model.sourceIndex)
                        }
                    }

                    ToolTip.visible: mouse.containsMouse && model.notes.length > 0
                    ToolTip.delay: 600
                    ToolTip.text: model.notes
                }
            }

            // Empty states — only after the first data load.
            ColumnLayout {
                anchors.centerIn: parent
                width: Math.min(parent.width - 32, 420)
                visible: account && account.loaded && list.count === 0
                spacing: 8
                Label {
                    Layout.fillWidth: true
                    text: root.filtered ? "No trades match your search" : "No trades yet"
                    color: app.theme.text
                    font.pixelSize: 13 * app.theme.fontScale
                    font.weight: Font.DemiBold
                    horizontalAlignment: Text.AlignHCenter
                }
                Label {
                    Layout.fillWidth: true
                    text: root.filtered
                        ? "Try another symbol or status, or clear the filters to see every trade."
                        : "Log a trade to start tracking your progress toward your goal."
                    color: app.theme.textMuted
                    font.pixelSize: 13 * app.theme.fontScale
                    wrapMode: Text.WordWrap
                    horizontalAlignment: Text.AlignHCenter
                }
                ToolButton2 {
                    Layout.alignment: Qt.AlignHCenter
                    visible: root.filtered
                    text: "Clear filters"
                    onClicked: {
                        filterField.text = ""
                        account.setTextFilter("")
                        account.setStatusFilter("")
                    }
                }
            }
        }
    }
}
