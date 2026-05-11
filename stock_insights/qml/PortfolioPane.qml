import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

ColumnLayout {
    id: root
    spacing: 0

    // Custom modern tab bar (one tab per account)
    Rectangle {
        Layout.fillWidth: true
        height: 42
        color: "transparent"

        RowLayout {
            anchors.fill: parent
            spacing: 4

            Repeater {
                model: app.accounts
                delegate: Rectangle {
                    id: tab
                    property bool active: index === app.currentAccountIndex
                    property bool hovered: false
                    height: parent.height
                    Layout.preferredWidth: Math.max(110, label.implicitWidth + 28)
                    radius: 10
                    // Active tab uses the card background to "lift" out of
                    // the pane background; inactive tabs stay flat.
                    color: tab.active ? app.theme.card
                         : (tab.hovered ? app.theme.cardAlt : "transparent")
                    border.color: tab.active ? app.theme.border : "transparent"
                    border.width: 1

                    // Active-tab accent stripe along the bottom — primary
                    // color makes the active selection unmistakable and
                    // visually rhymes with the +Trade button + Goal Target.
                    Rectangle {
                        visible: tab.active
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        anchors.leftMargin: 12
                        anchors.rightMargin: 12
                        height: 3
                        radius: 1.5
                        color: app.theme.primary
                    }

                    Behavior on color { ColorAnimation { duration: 150 } }
                    Behavior on border.color { ColorAnimation { duration: 150 } }

                    Label {
                        id: label
                        anchors.centerIn: parent
                        text: modelData.name
                        // Active tab text picks up the theme's primary
                        // color — same accent as the bottom stripe.
                        color: tab.active ? app.theme.primary
                             : (tab.hovered ? app.theme.text : app.theme.textMuted)
                        font.pointSize: 10 * app.theme.fontScale
                        font.weight: tab.active ? Font.DemiBold : Font.Normal
                    }

                    MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onEntered: tab.hovered = true
                        onExited:  tab.hovered = false
                        onClicked: app.setCurrentAccountIndex(index)
                    }
                }
            }

            Item { Layout.fillWidth: true }
        }
    }

    // Card-style content area
    Rectangle {
        Layout.fillWidth: true
        Layout.fillHeight: true
        color: app.theme.card
        border.color: app.theme.border
        border.width: 1
        radius: 12
        // Defense in depth — if the inner cards' sum-of-minimums ever
        // exceeds the available height (e.g. user shrank below the
        // documented window minimum via Aero Snap, or a future font-scale
        // pushes content past its Layout.minimumHeight), clip the
        // overflow at the rounded border instead of letting it leak
        // past the window's content area.
        clip: true

        PortfolioView {
            anchors.fill: parent
            anchors.margins: 12
            account: app.currentAccount
        }
    }
}
