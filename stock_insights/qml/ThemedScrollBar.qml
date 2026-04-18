import QtQuick
import QtQuick.Controls

// Reusable themed vertical scrollbar. Lives on the right edge of a
// ListView via `ScrollBar.vertical: ThemedScrollBar { }`. All three
// tables (Watchlist, Holdings, Trades) use this one definition so
// they stay visually consistent when the theme changes.
ScrollBar {
    id: root
    policy: ScrollBar.AsNeeded
    implicitWidth: 8
    minimumSize: 0.06        // minimum thumb length as a fraction of track

    // Narrow background track — fades to a subtle card-alt shade only
    // while the bar is visible so it doesn't distract when there's
    // nothing to scroll.
    background: Rectangle {
        color: app.theme.cardAlt
        opacity: 0.4
        radius: 3
    }

    // Thumb — picks up the theme's secondary accent so it matches the
    // section-title bars and the goal progress-bar gradient. Opacity
    // modulates based on interaction state for a smooth "wake up" feel.
    contentItem: Rectangle {
        implicitWidth: 6
        implicitHeight: 20
        radius: 3
        color: app.theme.secondary
        opacity: root.pressed ? 0.85
               : root.hovered ? 0.65
               : root.active  ? 0.45
                              : 0.28
        Behavior on opacity { NumberAnimation { duration: 120 } }
    }
}
