import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Section header with a small colored accent bar — the bar is the one
// consistent "theme pop" that appears on every card, giving them a shared
// visual anchor while picking up whichever accent each theme defines.
RowLayout {
    id: root
    property string title: ""
    property string subtitle: ""
    // Optional override — e.g. pass app.theme.good for the section of a
    // card that should read as "profitable". Default: the theme's secondary
    // accent color.
    property color accent: app.theme.secondary
    spacing: 10

    Rectangle {
        Layout.preferredWidth: 3
        Layout.preferredHeight: 16
        Layout.alignment: Qt.AlignVCenter
        radius: 1.5
        color: root.accent
    }

    Label {
        text: root.title
        color: app.theme.text
        font.pointSize: 11 * app.theme.fontScale
        font.weight: Font.DemiBold
        verticalAlignment: Text.AlignVCenter
    }
    Label {
        visible: root.subtitle.length > 0
        text: root.subtitle
        color: app.theme.textMuted
        font.pointSize: 10 * app.theme.fontScale
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        elide: Label.ElideRight
        horizontalAlignment: Text.AlignLeft
        verticalAlignment: Text.AlignVCenter
    }
}
