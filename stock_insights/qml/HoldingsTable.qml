import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "."

// Open positions. Sized to its rows (up to `maxVisibleRows`, then it
// scrolls) so the page never shows a tall empty box.
// Right-click a row (or press the Menu key) for Close / Mark down / etc.
Card {
    id: root
    property var account: null
    property int maxVisibleRows: 6
    readonly property int rowH: 32

    // key: model role; w: relative width; right: numeric (right-aligned);
    // pl: coloured by unrealizedSign.
    readonly property var cols: [
        { key: "instrument",        label: "Symbol",         w: 1.3 },
        { key: "qtyText",           label: "Shares",         w: 0.7, right: true },
        { key: "avgCost",           label: "Avg cost",       w: 1.0, right: true },
        { key: "mark",              label: "Price",          w: 1.0, right: true },
        { key: "marketValue",       label: "Market value",   w: 1.2, right: true },
        { key: "unrealizedPl",      label: "Unrealized P/L", w: 1.2, right: true, pl: true },
        { key: "unrealizedPctText", label: "Change",         w: 0.9, right: true, pl: true },
        { key: "weight",            label: "Weight",         w: 0.8, right: true }
    ]

    SectionTitle {
        title: "Open positions"
        subtitle: account && account.summary && list.count > 0
            ? account.summary.marketValue + " market value, " + account.summary.unrealizedPl + " unrealized"
            : ""
    }

    ColumnLayout {
        Layout.fillWidth: true
        spacing: 0

        // Header: card2 band, muted 12 px / 600.
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: root.rowH
            visible: list.count > 0
            color: app.theme.cardAlt
            radius: 6

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 4
                anchors.rightMargin: 4 + 10   // + scrollbar gutter
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

        ListView {
            id: list
            Layout.fillWidth: true
            Layout.preferredHeight: count > 0 ? Math.min(count, root.maxVisibleRows) * root.rowH : 0
            model: account ? account.holdings : null
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            currentIndex: -1
            activeFocusOnTab: count > 0
            keyNavigationEnabled: true
            ScrollBar.vertical: ThemedScrollBar { }
            Keys.onMenuPressed: if (currentItem) app.showHoldingsMenu(currentItem.symbol)
            Accessible.role: Accessible.Table
            Accessible.name: "Open positions"

            delegate: Rectangle {
                id: row
                readonly property string symbol: model.instrument
                readonly property var rowModel: model
                width: ListView.view.width
                height: root.rowH
                color: mouse.containsMouse || ListView.isCurrentItem ? app.theme.cardAlt : "transparent"

                // Hairline between rows (not after the last one).
                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    height: 1
                    color: app.theme.border
                    visible: index < list.count - 1
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 4
                    anchors.rightMargin: 4 + 10
                    spacing: 0
                    Repeater {
                        model: root.cols
                        Item {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            Layout.preferredWidth: modelData.w * 1000
                            Layout.minimumWidth: 24

                            Label {
                                id: cell
                                anchors.fill: parent
                                anchors.rightMargin: badge.visible ? badge.width + 8 : 0
                                text: row.rowModel[modelData.key]
                                color: modelData.pl
                                    ? (row.rowModel.unrealizedSign > 0 ? app.theme.good
                                       : row.rowModel.unrealizedSign < 0 ? app.theme.bad : app.theme.text)
                                    : (modelData.key === "weight" ? app.theme.textMuted : app.theme.text)
                                font.pixelSize: 13 * app.theme.fontScale
                                font.weight: modelData.key === "instrument" || modelData.key === "unrealizedPl"
                                             ? Font.DemiBold : Font.Normal
                                horizontalAlignment: modelData.right ? Text.AlignRight : Text.AlignLeft
                                verticalAlignment: Text.AlignVCenter
                                leftPadding: 8
                                rightPadding: 8
                                elide: Label.ElideRight
                            }
                            // "Short" badge after the symbol.
                            Rectangle {
                                id: badge
                                visible: modelData.key === "instrument" && row.rowModel.isShort
                                anchors.verticalCenter: parent.verticalCenter
                                x: Math.min(cell.contentWidth + 14, parent.width - width)
                                width: badgeText.implicitWidth + 12
                                height: 20
                                radius: 10
                                color: app.theme.cardAlt
                                border.width: 1
                                border.color: app.theme.border
                                Label {
                                    id: badgeText
                                    anchors.centerIn: parent
                                    text: "Short"
                                    color: app.theme.textMuted
                                    font.pixelSize: 12 * app.theme.fontScale
                                }
                            }
                        }
                    }
                }

                MouseArea {
                    id: mouse
                    anchors.fill: parent
                    hoverEnabled: true
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    onClicked: function (mouse) {
                        list.currentIndex = index
                        if (mouse.button === Qt.RightButton) app.showHoldingsMenu(model.instrument)
                    }
                }
            }
        }

        // Empty state — only after the first data load.
        ColumnLayout {
            Layout.fillWidth: true
            Layout.topMargin: 4
            visible: account && account.loaded && list.count === 0
            spacing: 2
            Label {
                text: "No open positions"
                color: app.theme.text
                font.pixelSize: 13 * app.theme.fontScale
                font.weight: Font.DemiBold
            }
            Label {
                text: "Log a trade to start tracking what you hold."
                color: app.theme.textMuted
                font.pixelSize: 13 * app.theme.fontScale
            }
        }
    }
}
