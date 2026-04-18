import QtQuick
import QtQuick.Controls

// Compact filled button used at the bottom of cards.
Button {
    id: root
    property bool primary: false

    leftPadding: 14
    rightPadding: 14
    topPadding: 8
    bottomPadding: 8
    font.pointSize: 9
    font.weight: Font.DemiBold

    contentItem: Label {
        text: root.text
        font: root.font
        color: root.primary ? app.theme.textOnColor : app.theme.text
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Label.ElideRight
    }

    background: Rectangle {
        radius: 8
        // Primary buttons pick up the theme's primary accent — the same
        // hue used by Goal Target + selected preset pills + hero metric,
        // creating a consistent "this is the main action / value" signal.
        color: root.primary
            ? (root.down ? Qt.darker(app.theme.primary, 1.1)
              : root.hovered ? Qt.lighter(app.theme.primary, 1.05)
              : app.theme.primary)
            : (root.down ? app.theme.cardAlt
              : root.hovered ? Qt.lighter(app.theme.button, 1.04)
              : app.theme.button)
        border.color: root.primary ? app.theme.primary : app.theme.border
        border.width: 1
        Behavior on color { ColorAnimation { duration: 120 } }
    }
}
