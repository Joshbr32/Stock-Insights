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
        color: root.primary
            ? (root.down ? Qt.darker(app.theme.secondary, 1.1)
              : root.hovered ? Qt.lighter(app.theme.secondary, 1.05)
              : app.theme.secondary)
            : (root.down ? app.theme.cardAlt
              : root.hovered ? Qt.lighter(app.theme.button, 1.04)
              : app.theme.button)
        border.color: root.primary ? app.theme.secondary : app.theme.border
        border.width: 1
    }
}
