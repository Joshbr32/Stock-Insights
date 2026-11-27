import QtQuick

// Harbor focus ring: 2 px `primary`, drawn 3 px outside the control so it
// never covers content. Place inside a control and bind `shown` to the
// control's visualFocus (keyboard focus only, not mouse clicks).
Rectangle {
    property bool shown: false
    property real controlRadius: 6
    anchors.fill: parent
    anchors.margins: -3
    radius: controlRadius + 3
    color: "transparent"
    border.width: 2
    border.color: app.theme.primary
    visible: shown
}
