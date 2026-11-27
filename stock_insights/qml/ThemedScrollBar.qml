import QtQuick
import QtQuick.Controls.Basic

// Quiet vertical scrollbar shared by every list: a thin `border`-coloured
// thumb that darkens on hover. No track.
ScrollBar {
    id: root
    policy: ScrollBar.AsNeeded
    implicitWidth: 10
    padding: 2
    minimumSize: 0.06

    background: Item {}

    contentItem: Rectangle {
        implicitWidth: 6
        implicitHeight: 24
        radius: 3
        color: root.pressed || root.hovered ? app.theme.textMuted : app.theme.border
        opacity: root.size < 1.0 ? 1.0 : 0.0
    }
}
