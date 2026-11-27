import QtQuick
import QtQuick.Controls.Basic

// The pace rail — the one bold element of the Harbor design.
//
//   |=========●==========|----------------------------|
//   $0      $3,475     Today's pace $4,504        $5,000
//
// Track from $0 to the goal; filled up to realized P/L ending in a dot; a
// thin amber `pace` tick where the user should be today. Amber is used
// nowhere else except the matching line on the equity curve.
//
// `pace` is AccountController.pace (see qml_bridge.py for its keys).
// Call play() to run the one-shot 0 -> value fill (400 ms, ease-out).
Item {
    id: rail
    property var pace: ({})
    readonly property real fraction: pace && pace.fraction !== undefined ? pace.fraction : 0
    readonly property real paceFraction: pace && pace.paceFraction !== undefined ? pace.paceFraction : 0
    readonly property bool hasGoal: pace && pace.state !== undefined && pace.state !== "none"
    // Drawn fill; bound to `fraction` except while the intro animation runs.
    property real shown: fraction

    implicitHeight: 48
    Accessible.role: Accessible.ProgressBar
    Accessible.name: hasGoal
        ? "Realized " + pace.realizedText + " of " + pace.targetText
          + ". Today's pace " + pace.expectedText + ". " + pace.sentence
        : "No goal set"

    function play() {
        if (app.theme.reduceMotion) {
            rail.shown = Qt.binding(function () { return rail.fraction })
            return
        }
        intro.to = rail.fraction
        intro.restart()
    }

    NumberAnimation {
        id: intro
        target: rail
        property: "shown"
        from: 0
        duration: 400
        easing.type: Easing.OutCubic
        onFinished: rail.shown = Qt.binding(function () { return rail.fraction })
    }

    readonly property real trackW: width
    readonly property real dotX: Math.max(0, Math.min(trackW, trackW * shown))
    readonly property real tickX: trackW * paceFraction

    // ── Track, fill, tick, dot ───────────────────────────────────────────
    Item {
        id: lane
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: 20

        Rectangle {
            id: track
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width
            height: 8
            radius: 4
            color: app.theme.border
        }
        Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            width: rail.dotX
            height: 8
            radius: 4
            color: app.theme.primary
            visible: rail.hasGoal
        }
        Rectangle {
            // Today's pace. 2 px wide, taller than the track so it reads as
            // a marker rather than part of the fill.
            visible: rail.hasGoal
            x: Math.max(0, Math.min(rail.trackW - width, rail.tickX - width / 2))
            anchors.verticalCenter: parent.verticalCenter
            width: 2
            height: 20
            radius: 1
            color: app.theme.pace
        }
        Rectangle {
            visible: rail.hasGoal
            width: 16
            height: 16
            radius: 8
            x: Math.max(0, Math.min(rail.trackW - width, rail.dotX - width / 2))
            anchors.verticalCenter: parent.verticalCenter
            color: app.theme.primary
            border.width: 3
            border.color: app.theme.card
        }
    }

    // ── Labels under the rail; any that would collide are dropped ────────
    Item {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: lane.bottom
        anchors.topMargin: 8
        height: 18
        visible: rail.hasGoal

        Label {
            id: zeroLabel
            text: "$0"
            color: app.theme.textMuted
            font.pixelSize: 12 * app.theme.fontScale
            visible: dotLabel.x > width + 12 || !dotLabel.visible
        }
        Label {
            id: dotLabel
            text: rail.pace.realizedText || ""
            color: app.theme.text
            font.pixelSize: 12 * app.theme.fontScale
            font.weight: Font.DemiBold
            x: Math.max(0, Math.min(rail.trackW - width, rail.dotX - width / 2))
            // Hidden when it would overlap the pace label: the hero number
            // above already states the same value.
            visible: Math.abs(rail.dotX - rail.tickX) > (width + paceLabel.width) / 2 + 12
                     && (x + width < targetLabel.x - 12 || rail.fraction >= 1)
        }
        Label {
            id: paceLabel
            text: "Today's pace " + (rail.pace.expectedText || "")
            color: app.theme.textMuted
            font.pixelSize: 12 * app.theme.fontScale
            x: Math.max(0, Math.min(rail.trackW - width, rail.tickX - width / 2))
        }
        Label {
            id: targetLabel
            text: rail.pace.targetText || ""
            anchors.right: parent.right
            color: app.theme.textMuted
            font.pixelSize: 12 * app.theme.fontScale
            visible: paceLabel.x + paceLabel.width < x - 12
                     && (!dotLabel.visible || dotLabel.x + dotLabel.width < x - 12)
        }
    }
}
