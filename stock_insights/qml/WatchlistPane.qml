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
            spacing: 2
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            delegate: Rectangle {
                width: list.width
                height: 34
                radius: 6
                color: list.currentIndex === index
                    ? app.theme.cardAlt
                    : (mouse.containsMouse ? Qt.lighter(app.theme.cardAlt, 1.06) : "transparent")

                Behavior on color { ColorAnimation { duration: 100 } }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 10
                    anchors.rightMargin: 10
                    spacing: 12

                    Label {
                        text: model.symbol
                        color: app.theme.text
                        font.pointSize: 10
                        font.weight: Font.DemiBold
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        horizontalAlignment: Text.AlignLeft
                        verticalAlignment: Text.AlignVCenter
                        elide: Label.ElideRight
                    }
                    Label {
                        text: model.priceText
                        color: model.price === undefined || model.price === null
                            ? app.theme.textMuted
                            : app.theme.text
                        font.pointSize: 10
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
