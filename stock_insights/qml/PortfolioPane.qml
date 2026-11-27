import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "."

// Right column: one text tab per account, the app's main action
// ("Log trade") on the right, and the selected account's view below.
ColumnLayout {
    id: root
    spacing: 12

    RowLayout {
        Layout.fillWidth: true
        Layout.fillHeight: false
        Layout.preferredHeight: 36
        spacing: 4

        Repeater {
            model: app.accounts
            delegate: AbstractButton {
                id: tab
                property bool active: index === app.currentAccountIndex
                Layout.fillHeight: true
                implicitWidth: label.implicitWidth + 24
                hoverEnabled: true
                activeFocusOnTab: true
                Accessible.role: Accessible.PageTab
                Accessible.name: modelData.name
                Accessible.checked: active
                onClicked: app.setCurrentAccountIndex(index)

                contentItem: Label {
                    id: label
                    text: modelData.name
                    color: tab.active || tab.hovered ? app.theme.text : app.theme.textMuted
                    font.pixelSize: 15 * app.theme.fontScale
                    font.weight: Font.DemiBold
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                background: Item {
                    // Selected tab: 2 px primary underline.
                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        anchors.leftMargin: 12
                        anchors.rightMargin: 12
                        height: 2
                        radius: 1
                        color: app.theme.primary
                        visible: tab.active
                    }
                    FocusRing { shown: tab.visualFocus; controlRadius: 6; anchors.margins: 0 }
                }
            }
        }

        Item { Layout.fillWidth: true }

        ToolButton2 {
            text: "Log trade"
            primary: true
            Layout.alignment: Qt.AlignVCenter
            onClicked: app.addTrade()
        }
    }

    PortfolioView {
        id: view
        Layout.fillWidth: true
        Layout.fillHeight: true
        account: app.currentAccount
    }

    // Tab switch cross-fade (120 ms); skipped when the OS asks for less motion.
    NumberAnimation {
        id: fadeIn
        target: view
        property: "opacity"
        from: 0.35
        to: 1
        duration: 120
        easing.type: Easing.OutQuad
    }
    Connections {
        target: app
        function onCurrentAccountChanged() {
            if (!app.theme.reduceMotion) fadeIn.restart()
        }
    }
}
