import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "."

// Left column: watched symbols with their latest price.
// Keyboard: Tab into the list, Up/Down to move, Delete to remove.
Card {
    id: root
    padding: 12

    SectionTitle {
        Layout.leftMargin: 4
        title: "Watchlist"
        // `count` is a notifying property; rowCount() would not re-evaluate.
        subtitle: app.watchlist.count === 1 ? "1 symbol" : app.watchlist.count + " symbols"
    }

    Item {
        Layout.fillWidth: true
        Layout.fillHeight: true

        ListView {
            id: list
            anchors.fill: parent
            model: app.watchlist
            clip: true
            currentIndex: -1
            boundsBehavior: Flickable.StopAtBounds
            activeFocusOnTab: true
            keyNavigationEnabled: true
            ScrollBar.vertical: ThemedScrollBar { }
            Keys.onDeletePressed: if (currentIndex >= 0) app.removeTicker(currentIndex)
            Accessible.role: Accessible.List
            Accessible.name: "Watchlist"

            delegate: Rectangle {
                id: row
                width: ListView.view.width
                height: 32
                radius: 6
                property bool selected: ListView.isCurrentItem
                color: row.selected ? app.theme.cardAlt : "transparent"

                // Hover tint: same tone as selection, lighter.
                Rectangle {
                    anchors.fill: parent
                    radius: 6
                    color: app.theme.cardAlt
                    opacity: mouse.containsMouse && !row.selected ? 0.6 : 0
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 10
                    anchors.rightMargin: 12
                    spacing: 8

                    Label {
                        text: model.symbol
                        color: app.theme.text
                        font.pixelSize: 13 * app.theme.fontScale
                        font.weight: Font.DemiBold
                        Layout.fillWidth: true
                        elide: Label.ElideRight
                    }
                    Label {
                        text: model.price === undefined || model.price === null ? "No price" : model.priceText
                        color: model.price === undefined || model.price === null
                               ? app.theme.textMuted : app.theme.text
                        font.pixelSize: 13 * app.theme.fontScale
                        horizontalAlignment: Text.AlignRight
                    }
                }

                MouseArea {
                    id: mouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: { list.currentIndex = index; list.forceActiveFocus() }
                }
            }

            // Focus ring around the list when it holds keyboard focus.
            FocusRing { shown: list.activeFocus && list.currentIndex < 0; controlRadius: 6; anchors.margins: 0 }
        }

        Label {
            anchors.centerIn: parent
            width: parent.width - 24
            visible: app.watchlist.count === 0
            text: "Your watchlist is empty. Add a symbol to see its price here."
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter
            color: app.theme.textMuted
            font.pixelSize: 13 * app.theme.fontScale
        }
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: 8

        ToolButton2 {
            text: "Add symbol"
            Layout.fillWidth: true
            onClicked: app.addTicker()
        }
        ToolButton2 {
            text: "Remove"
            Layout.fillWidth: true
            enabled: list.currentIndex >= 0
            onClicked: app.removeTicker(list.currentIndex)
            ToolTip.visible: hovered && !enabled
            ToolTip.text: "Select a symbol first"
        }
    }
}
