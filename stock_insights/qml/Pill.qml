import QtQuick
import QtQuick.Controls

// Compact selectable preset pill used in the goal dashboard header.
Rectangle {
    id: root
    property string label: ""
    property bool selected: false
    signal clicked

    implicitHeight: 28
    implicitWidth: Math.max(48, txt.implicitWidth + 22)
    radius: height / 2
    // Selected pills use the theme's primary accent — this is the same
    // token the Goal Target hero number uses, so picking a preset feels
    // visually connected to the number it sets.
    color: selected ? app.theme.primary : "transparent"
    border.color: selected ? app.theme.primary : app.theme.border
    border.width: 1

    Behavior on color { ColorAnimation { duration: 120 } }
    Behavior on border.color { ColorAnimation { duration: 120 } }

    Label {
        id: txt
        anchors.centerIn: parent
        text: root.label
        color: root.selected ? app.theme.textOnColor : app.theme.text
        font.pointSize: 9
        font.weight: Font.DemiBold
    }

    MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        hoverEnabled: true
        onEntered: if (!root.selected) root.color = app.theme.cardAlt
        onExited:  if (!root.selected) root.color = "transparent"
        onClicked: root.clicked()
    }
}
