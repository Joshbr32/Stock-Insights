import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Harbor combo box. QtQuick.Controls ignores the widget QSS, so every part
// is drawn here: 32 px field on `cardAlt`, radius 6, 2 px focus ring,
// popup fades in over 100 ms (skipped with reduced motion).
ComboBox {
    id: root

    implicitHeight: 32
    leftPadding: 10
    rightPadding: 28
    font.pixelSize: 13 * app.theme.fontScale
    hoverEnabled: true

    background: Rectangle {
        radius: 6
        color: root.hovered && !root.pressed
            ? Qt.darker(app.theme.cardAlt, app.theme.isLight ? 1.03 : 0.9)
            : app.theme.cardAlt
        border.width: 1
        border.color: app.theme.border

        FocusRing { shown: root.visualFocus; controlRadius: 6 }
    }

    contentItem: Label {
        text: root.displayText
        color: app.theme.text
        font: root.font
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    indicator: Canvas {
        id: chevron
        x: root.width - width - 10
        y: (root.height - height) / 2
        width: 10
        height: 6
        property color stroke: app.theme.textMuted
        onStrokeChanged: requestPaint()
        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            ctx.strokeStyle = stroke
            ctx.lineWidth = 1.6
            ctx.lineCap = "round"
            ctx.lineJoin = "round"
            ctx.beginPath()
            ctx.moveTo(1, 1)
            ctx.lineTo(width / 2, height - 1)
            ctx.lineTo(width - 1, 1)
            ctx.stroke()
        }
    }

    popup: Popup {
        y: root.height + 4
        width: Math.max(root.width, 140)
        padding: 4
        implicitHeight: Math.min(contentItem.implicitHeight + 8, 320)

        enter: Transition {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: app.theme.reduceMotion ? 0 : 100 }
        }

        background: Rectangle {
            radius: 6
            color: app.theme.card
            border.color: app.theme.border
            border.width: 1
        }
        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: root.popup.visible ? root.delegateModel : null
            currentIndex: root.highlightedIndex
            ScrollBar.vertical: ThemedScrollBar { }
        }
    }

    delegate: ItemDelegate {
        width: ListView.view ? ListView.view.width : root.width
        height: 32
        hoverEnabled: true
        contentItem: Label {
            text: modelData
            color: app.theme.text
            font.pixelSize: 13 * app.theme.fontScale
            font.weight: root.currentIndex === index ? Font.DemiBold : Font.Normal
            verticalAlignment: Text.AlignVCenter
            leftPadding: 6
            elide: Text.ElideRight
        }
        background: Rectangle {
            radius: 4
            color: root.highlightedIndex === index || hovered ? app.theme.cardAlt : "transparent"
        }
    }
}
