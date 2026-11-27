import QtQuick
import QtQuick.Controls.Basic

// Harbor button: 32 px tall, radius 6. `primary: true` is the filled main
// action; otherwise a quiet secondary button on `cardAlt`.
Button {
    id: root
    property bool primary: false

    implicitHeight: 32
    leftPadding: 14
    rightPadding: 14
    topPadding: 0
    bottomPadding: 0
    font.pixelSize: 13 * app.theme.fontScale
    font.weight: Font.DemiBold
    hoverEnabled: true

    contentItem: Label {
        text: root.text
        font: root.font
        color: root.primary ? app.theme.textOnColor : app.theme.text
        opacity: root.enabled ? 1.0 : 0.45
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Label.ElideRight
    }

    background: Rectangle {
        implicitHeight: 32
        radius: 6
        color: root.primary
            ? (root.down ? Qt.darker(app.theme.primary, 1.12)
              : root.hovered ? Qt.darker(app.theme.primary, 1.06)
              : app.theme.primary)
            : (root.down ? app.theme.border
              : root.hovered && root.enabled ? Qt.darker(app.theme.cardAlt, app.theme.isLight ? 1.04 : 0.88)
              : app.theme.cardAlt)
        opacity: root.enabled || !root.primary ? 1.0 : 0.5

        FocusRing { shown: root.visualFocus; controlRadius: 6 }
    }
}
