import QtQuick
import QtQuick.Layouts

// Harbor panel ("deck"): `card` on the `bg` harbor, separated by tone only —
// no border, no shadow. Radius 10, padding 16.
//
// Only implicitHeight is published (from the inner layout) so parent
// layouts can size the card; width always comes from Layout.fillWidth,
// otherwise a wide subtitle or table row would push the card past its column.
Rectangle {
    id: root
    color: app.theme.card
    radius: 10
    // Keeps inner list views and scrollbars inside the rounded corners.
    clip: true

    default property alias content: container.data
    property int padding: 16
    property alias spacing: container.spacing

    implicitHeight: Math.max(48, container.implicitHeight + padding * 2)

    ColumnLayout {
        id: container
        anchors.fill: parent
        anchors.margins: root.padding
        spacing: 12
    }
}
