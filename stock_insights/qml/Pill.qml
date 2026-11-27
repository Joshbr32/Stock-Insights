import QtQuick
import QtQuick.Controls.Basic

// Fully round selectable chip (goal presets). Keyboard: Tab to focus,
// Space / Enter to choose.
Rectangle {
    id: root
    property string label: ""
    property bool selected: false
    signal clicked

    implicitHeight: 32
    implicitWidth: Math.max(52, txt.implicitWidth + 24)
    radius: height / 2
    activeFocusOnTab: true
    color: selected ? app.theme.primary
         : mouse.containsMouse ? app.theme.cardAlt : "transparent"
    border.width: selected ? 0 : 1
    border.color: app.theme.border

    Accessible.role: Accessible.Button
    Accessible.name: label
    Accessible.checkable: true
    Accessible.checked: selected
    Accessible.onPressAction: root.clicked()

    Keys.onSpacePressed: root.clicked()
    Keys.onReturnPressed: root.clicked()
    Keys.onEnterPressed: root.clicked()

    Label {
        id: txt
        anchors.centerIn: parent
        text: root.label
        color: root.selected ? app.theme.textOnColor : app.theme.text
        font.pixelSize: 13 * app.theme.fontScale
        font.weight: Font.DemiBold
        font.features: { "tnum": 1 }
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }

    FocusRing { shown: root.activeFocus; controlRadius: root.radius }
}
