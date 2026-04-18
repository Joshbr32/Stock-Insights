import QtQuick
import QtQuick.Layouts

// Reusable rounded panel with a soft border.
//
// Why the implicitWidth/Height bindings: a bare Rectangle has no implicit
// size. When a Card is placed inside a RowLayout/ColumnLayout, the parent
// layout asks the Card "how big do you want to be?" — without these
// bindings the answer is 0, the layout allocates 0 px, the inner
// ColumnLayout (which uses anchors.fill) shrinks to 0, and the entire
// section disappears. Publishing the inner layout's implicit size fixes that
// while still letting the Card grow when the parent layout sets fillWidth /
// fillHeight on it.
Rectangle {
    id: root
    color: app.theme.card
    border.color: app.theme.border
    border.width: 1
    radius: 12
    // Hard guarantee that nothing inside the card draws past its rounded
    // border — without this, an inner ListView's scrollbar or a row with
    // an oversized implicit width can visually escape the card outline.
    clip: true

    default property alias content: container.data
    property int padding: 16

    // Only publish implicit HEIGHT (so parent layouts that derive height from
    // children can size us). Width is always governed by Layout.fillWidth in
    // our usage; binding implicitWidth to container's widest child causes the
    // Card to overflow when an inner SectionTitle subtitle or table row gets
    // wider than the parent column.
    implicitHeight: Math.max(60, container.implicitHeight + padding * 2)

    ColumnLayout {
        id: container
        anchors.fill: parent
        anchors.margins: root.padding
        spacing: 10
    }
}
