import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Themed QML ComboBox — QtQuick.Controls' default style ignores the
// QApplication stylesheet (that's only applied to QWidgets), so we
// customize background / indicator / popup / delegates by hand.
// Picks up all the same theme tokens as every other control.
ComboBox {
    id: root

    implicitHeight: 36
    leftPadding: 12
    rightPadding: 30
    font.pointSize: 9 * app.theme.fontScale

    background: Rectangle {
        radius: 8
        color: app.theme.card
        border.color: root.activeFocus || root.pressed
            ? app.theme.secondary : app.theme.border
        border.width: 1
        Behavior on border.color { ColorAnimation { duration: 100 } }
    }

    contentItem: Label {
        text: root.displayText
        color: app.theme.text
        font: root.font
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    // Chevron indicator on the right — drawn in the same muted tone the
    // rest of the UI uses for secondary signifiers.
    indicator: Label {
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        rightPadding: 10
        text: "⌄"
        color: app.theme.textMuted
        font.pointSize: 12 * app.theme.fontScale
        font.weight: Font.DemiBold
    }

    // Popup menu — matches the card aesthetic with a rounded corner,
    // themed border, and item highlight using the primary accent.
    popup: Popup {
        y: root.height + 2
        width: root.width
        padding: 4
        background: Rectangle {
            radius: 8
            color: app.theme.card
            border.color: app.theme.border
            border.width: 1
        }
        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: root.popup.visible ? root.delegateModel : null
            currentIndex: root.highlightedIndex
            ScrollIndicator.vertical: ScrollIndicator { }
        }
    }

    delegate: ItemDelegate {
        width: root.width
        height: 30
        contentItem: Label {
            text: modelData
            color: root.highlightedIndex === index
                ? app.theme.textOnColor : app.theme.text
            font.pointSize: 9 * app.theme.fontScale
            verticalAlignment: Text.AlignVCenter
            leftPadding: 10
        }
        background: Rectangle {
            radius: 6
            color: root.highlightedIndex === index
                ? app.theme.primary
                : (hovered ? app.theme.cardAlt : "transparent")
            Behavior on color { ColorAnimation { duration: 80 } }
        }
    }
}
