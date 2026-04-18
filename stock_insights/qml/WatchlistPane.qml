import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

Card {
    id: root
    padding: 14

    SectionTitle {
        title: "Watchlist"
        // Bind to the count Q_PROPERTY so the subtitle updates when the
        // model is reset (rowCount() is a method and won't notify).
        subtitle: app.watchlist.count + (app.watchlist.count === 1 ? " symbol" : " symbols")
    }

    Rectangle {
        Layout.fillWidth: true
        Layout.preferredHeight: 1
        color: app.theme.border
    }

    Rectangle {
        Layout.fillWidth: true
        Layout.fillHeight: true
        color: "transparent"
        clip: true

        ListView {
            id: list
            anchors.fill: parent
            // Reserve a strip on the right so the floating scrollbar never
            // sits on top of the row text.
            anchors.rightMargin: 10
            model: app.watchlist
            spacing: 1
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ThemedScrollBar { }

            delegate: Rectangle {
                id: row
                width: list.width
                height: 32
                radius: 4

                // Shared row-state model (see HoldingsTable / TradesTable):
                //   selected → filled with app.theme.primary  (same hue as
                //              the `+ Add` / `+ Trade` buttons, so "selected"
                //              and "primary action" share a visual vocabulary)
                //   hovered  → 1.5 px primary-colored outline around the
                //              normal base, providing strong feedback without
                //              competing with the selected fill
                //   odd row  → subtle zebra stripe
                //   even row → transparent (card bg shows through)
                property bool selected: list.currentIndex === index
                property bool hovered:  mouse.containsMouse

                color: row.selected
                    ? app.theme.primary
                    : (index % 2 === 0 ? "transparent"
                                       : Qt.lighter(app.theme.cardAlt, 1.02))
                border.color: row.hovered && !row.selected
                    ? app.theme.primary : "transparent"
                border.width: 1.5

                Behavior on color        { ColorAnimation { duration: 100 } }
                Behavior on border.color { ColorAnimation { duration: 100 } }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 10
                    anchors.rightMargin: 10
                    spacing: 12

                    Label {
                        text: model.symbol
                        // When the row is filled with the primary accent,
                        // switch text to textOnColor so it stays readable.
                        color: row.selected ? app.theme.textOnColor : app.theme.text
                        font.pointSize: 10 * app.theme.fontScale
                        font.weight: Font.DemiBold
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        horizontalAlignment: Text.AlignLeft
                        verticalAlignment: Text.AlignVCenter
                        elide: Label.ElideRight
                    }
                    Label {
                        text: model.priceText
                        color: row.selected
                            ? app.theme.textOnColor
                            : (model.price === undefined || model.price === null
                                ? app.theme.textMuted : app.theme.text)
                        font.pointSize: 10 * app.theme.fontScale
                        Layout.fillHeight: true
                        horizontalAlignment: Text.AlignLeft
                        verticalAlignment: Text.AlignVCenter
                    }
                }

                MouseArea {
                    id: mouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: list.currentIndex = index
                }
            }
        }
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: 8

        ToolButton2 {
            text: "+ Add"
            primary: true
            Layout.fillWidth: true
            onClicked: app.addTicker()
        }
        ToolButton2 {
            text: "− Remove"
            Layout.fillWidth: true
            enabled: list.currentIndex >= 0
            onClicked: app.removeTicker(list.currentIndex)
        }
    }
}
