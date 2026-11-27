import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Label / value pair.
//   inline (default): label left, value right — statement-style lists.
//   stacked: label above a larger value — the goal metrics strip.
// `sign`: 0 = neutral, +1 = gain (good), -1 = loss (bad). Values already
// carry a +/− sign, so colour is never the only cue.
GridLayout {
    id: root
    property string label: ""
    property string value: "—"
    property int sign: 0
    property bool stacked: false

    columns: stacked ? 1 : 2
    columnSpacing: 12
    rowSpacing: 2

    Label {
        text: root.label
        color: app.theme.textMuted
        font.pixelSize: (root.stacked ? 12 : 13) * app.theme.fontScale
        Layout.fillWidth: true
        elide: Label.ElideRight
    }

    Label {
        text: root.value
        color: root.sign > 0 ? app.theme.good
             : root.sign < 0 ? app.theme.bad
             : app.theme.text
        font.pixelSize: (root.stacked ? 15 : 13) * app.theme.fontScale
        font.weight: Font.DemiBold
        font.features: { "tnum": 1 }
        horizontalAlignment: root.stacked ? Text.AlignLeft : Text.AlignRight
        Layout.fillWidth: root.stacked
    }
}
