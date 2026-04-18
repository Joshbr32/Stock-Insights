import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// One label / value row used inside Goal Dashboard and Analytics.
// `sign`:  0 = neutral, +1 = profit (good), -1 = loss (bad)
RowLayout {
    id: root
    property string label: ""
    property string value: "—"
    property int sign: 0

    spacing: 12

    Label {
        text: root.label
        color: app.theme.textMuted
        font.pointSize: 9 * app.theme.fontScale
        Layout.fillWidth: true
        elide: Label.ElideRight
    }

    Label {
        text: root.value
        color: root.sign > 0 ? app.theme.good
             : root.sign < 0 ? app.theme.bad
             : app.theme.text
        font.pointSize: 10 * app.theme.fontScale
        font.weight: Font.DemiBold
        horizontalAlignment: Text.AlignRight
    }
}
