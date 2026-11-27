import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "."

// Goal block: answers "am I on pace?" at a glance.
//   Goal $5,000 by Dec 31                      [$2.5K] [$5K] [$10K]
//   +$3,474.85                                   $1,029 behind pace
//   realized profit
//   <pace rail>
//   Unrealized | Year-end forecast | Left to goal | Needed per day / week | Trading days left
Card {
    id: root
    property var account: null
    padding: 20
    spacing: 14

    readonly property var goal: account && account.goal ? account.goal : ({})
    readonly property var pace: account && account.pace ? account.pace : ({})

    // Play the rail's fill animation once per account, the first time that
    // account's data is on screen.
    property var _seen: ({})
    function _maybePlay() {
        if (!account || !account.loaded || _seen[account.name]) return
        _seen[account.name] = true
        rail.play()
    }
    onAccountChanged: _maybePlay()
    Connections {
        target: root.account
        ignoreUnknownSignals: true
        function onLoadedChanged() { root._maybePlay() }
    }
    Component.onCompleted: _maybePlay()

    // ── Goal line + presets ─────────────────────────────────────────────
    RowLayout {
        Layout.fillWidth: true
        spacing: 8

        Label {
            text: "Goal"
            color: app.theme.textMuted
            font.pixelSize: 13 * app.theme.fontScale
        }
        Label {
            text: (root.pace.targetText || "—") + " " + (root.pace.endText || "")
            color: app.theme.text
            font.pixelSize: 13 * app.theme.fontScale
            font.weight: Font.DemiBold
        }
        Item { Layout.fillWidth: true }
        Label {
            text: "Change goal"
            color: app.theme.textMuted
            font.pixelSize: 12 * app.theme.fontScale
            visible: presetRow.count > 0 && root.width > 560
        }
        Repeater {
            id: presetRow
            model: account ? account.presets : []
            Pill {
                label: modelData.label
                selected: account && Math.abs(modelData.value - account.goalTargetValue) < 0.5
                onClicked: app.setGoalTarget(modelData.value)
            }
        }
    }

    // ── Hero number + pace sentence ─────────────────────────────────────
    RowLayout {
        Layout.fillWidth: true
        spacing: 16

        ColumnLayout {
            spacing: 0
            Label {
                text: root.goal.realized || "—"
                color: account && account.realizedSign < 0 ? app.theme.bad : app.theme.text
                font.family: app.theme.displayFontFamily
                font.pixelSize: 40 * app.theme.fontScale
                font.weight: Font.Bold
                font.features: { "tnum": 1 }
            }
            Label {
                text: "Realized profit"
                color: app.theme.textMuted
                font.pixelSize: 13 * app.theme.fontScale
            }
        }

        Item { Layout.fillWidth: true }

        Label {
            Layout.alignment: Qt.AlignTop
            Layout.topMargin: 12
            text: root.pace.sentence || ""
            color: root.pace.state === "behind" ? app.theme.bad
                 : (root.pace.state === "ahead" || root.pace.state === "reached") ? app.theme.good
                 : app.theme.textMuted
            font.pixelSize: 20 * app.theme.fontScale
            font.family: app.theme.displayFontFamily
            font.weight: Font.DemiBold
            horizontalAlignment: Text.AlignRight
        }
    }

    PaceRail {
        id: rail
        Layout.fillWidth: true
        Layout.topMargin: 2
        Layout.bottomMargin: 6
        pace: root.pace
    }

    // ── Supporting numbers ──────────────────────────────────────────────
    GridLayout {
        Layout.fillWidth: true
        columns: root.width > 820 ? 6 : 3
        columnSpacing: 24
        rowSpacing: 12

        Metric {
            Layout.fillWidth: true
            stacked: true
            label: "Unrealized"
            value: root.goal.unrealized || "—"
            sign: root.goal.unrealizedSign || 0
        }
        Metric {
            Layout.fillWidth: true
            stacked: true
            label: "Year-end forecast"
            value: root.goal.yearEndForecast || "—"
            sign: root.goal.yearEndForecastSign || 0
        }
        Metric {
            Layout.fillWidth: true
            stacked: true
            label: "Left to goal"
            value: (root.goal.remainingSign || 0) < 0 ? "Nothing left" : (root.goal.remaining || "—")
        }
        Metric {
            Layout.fillWidth: true
            stacked: true
            label: "Needed per day"
            value: (root.goal.remainingSign || 0) < 0 ? "—" : (root.goal.daily || "—")
        }
        Metric {
            Layout.fillWidth: true
            stacked: true
            label: "Needed per week"
            value: (root.goal.remainingSign || 0) < 0 ? "—" : (root.goal.weekly || "—")
        }
        Metric {
            Layout.fillWidth: true
            stacked: true
            label: "Trading days left"
            value: root.goal.daysRemaining || "—"
        }
    }
}
