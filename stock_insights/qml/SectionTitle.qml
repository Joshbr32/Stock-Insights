import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Panel heading: title (15 px, 600) and an optional muted subtitle that
// reads as a plain phrase ("32 trades, all time").
RowLayout {
    id: root
    property string title: ""
    property string subtitle: ""
    // Kept for API compatibility; Harbor headings have no accent bar.
    property color accent: app.theme.primary
    spacing: 8

    Label {
        text: root.title
        color: app.theme.text
        font.pixelSize: 15 * app.theme.fontScale
        font.weight: Font.DemiBold
        verticalAlignment: Text.AlignVCenter
        Accessible.role: Accessible.Heading
    }
    Label {
        visible: root.subtitle.length > 0
        text: root.subtitle
        color: app.theme.textMuted
        font.pixelSize: 13 * app.theme.fontScale
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        elide: Label.ElideRight
        verticalAlignment: Text.AlignVCenter
    }
}
