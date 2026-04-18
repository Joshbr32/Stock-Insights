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
                    height: parent.height
                    Layout.preferredWidth: Math.max(110, label.implicitWidth + 28)
                    radius: 10
                    color: active ? app.theme.card : "transparent"
                    border.color: active ? app.theme.border : "transparent"
                    border.width: 1

                    // Active-tab accent stripe along the top
                    Rectangle {
                        visible: tab.active
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        height: 2
                        radius: 1
                        color: app.theme.secondary
                    }

                    Behavior on color { ColorAnimation { duration: 150 } }
                    Behavior on border.color { ColorAnimation { duration: 150 } }

                    Label {
                        id: label
                        anchors.centerIn: parent
                        text: modelData.name
                        color: tab.active ? app.theme.text : app.theme.textMuted
                        font.pointSize: 10
                        font.weight: tab.active ? Font.DemiBold : Font.Normal
                    }

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
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

        PortfolioView {
            anchors.fill: parent
            anchors.margins: 12
            account: app.currentAccount
        }
    }
}
