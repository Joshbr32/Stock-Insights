import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

RowLayout {
    id: root
    property string title: ""
    property string subtitle: ""
    spacing: 8

    Label {
        text: root.title
        color: app.theme.text
        font.pointSize: 11
        font.weight: Font.DemiBold
    }
    Label {
        // Subtitle takes whatever horizontal space remains after the title
        // and elides if it's too long. Without elide + fillWidth, a long
        // subtitle would push the parent Card past its allotted width.
        visible: root.subtitle.length > 0
        text: root.subtitle
        color: app.theme.textMuted
        font.pointSize: 10
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        elide: Label.ElideRight
        horizontalAlignment: Text.AlignLeft
    }
}
