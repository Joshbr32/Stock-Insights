import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

Card {
    id: root
    property var account: null
    padding: 16

    // Picks a color for the Realized Profit hero based on whether the
    // user is in the green or in the red. Zero / no-data falls back to
    // the theme's primary so the split hero still visually balances.
    function realizedColor() {
        if (!account) return app.theme.primary
        var s = account.realizedSign
        if (s > 0) return app.theme.good
        if (s < 0) return app.theme.bad
        return app.theme.primary
    }

    SectionTitle {
        title: "Goal Dashboard"
        subtitle: account ? account.name : ""
    }

    // ── Split hero: Annual Target (left) + Realized Profit (right) ─────────
    RowLayout {
        Layout.fillWidth: true
        spacing: 18

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 2
            Label {
                text: "Annual Target"
                color: app.theme.textMuted
                font.pointSize: 9
                font.weight: Font.DemiBold
            }
            Label {
                text: account && account.goal ? (account.goal.target || "—") : "—"
                color: app.theme.primary
                font.pointSize: 18
                font.weight: Font.Bold
                elide: Label.ElideRight
                Layout.fillWidth: true
            }
        }

        // Slim vertical divider between the two hero numbers — makes the
        // split visually crisp without needing extra labels or borders.
        Rectangle {
            Layout.preferredWidth: 1
            Layout.preferredHeight: 44
            Layout.alignment: Qt.AlignVCenter
            color: app.theme.border
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 2
            Label {
                text: "Realized Profit"
                color: app.theme.textMuted
                font.pointSize: 9
                font.weight: Font.DemiBold
                horizontalAlignment: Text.AlignRight
                Layout.fillWidth: true
            }
            Label {
                text: account && account.goal ? (account.goal.realized || "—") : "—"
                color: realizedColor()
                font.pointSize: 18
                font.weight: Font.Bold
                horizontalAlignment: Text.AlignRight
                elide: Label.ElideRight
                Layout.fillWidth: true
            }
        }
    }

    // ── Goal progress bar ──────────────────────────────────────────────────
    RowLayout {
        Layout.fillWidth: true
        spacing: 10

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 6
            color: app.theme.cardAlt
            radius: 3

            Rectangle {
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                width: parent.width * (account ? account.goalProgressPct / 100 : 0)
                radius: 3
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0.0; color: app.theme.primary }
                    GradientStop { position: 1.0; color: app.theme.secondary }
                }
                Behavior on width { NumberAnimation { duration: 250; easing.type: Easing.OutCubic } }
            }
        }
        Label {
            text: (account ? account.goalProgressPct.toFixed(1) : "0") + "%"
            color: app.theme.textMuted
            font.pointSize: 9
            font.weight: Font.DemiBold
            Layout.minimumWidth: 44
            horizontalAlignment: Text.AlignRight
        }
    }

    // ── Preset pills — moved out of the hero row so the Target/Realized
    // split has room to breathe. Still visually tied to the hero because
    // tapping one updates the Annual Target number right above.
    RowLayout {
        Layout.fillWidth: true
        spacing: 8
        Label {
            text: "Preset Targets"
            color: app.theme.textMuted
            font.pointSize: 9
        }
        Repeater {
            model: account ? account.presets : []
            Pill {
                label: modelData.label
                selected: account && Math.abs(modelData.value - account.goalTargetValue) < 0.5
                onClicked: app.setGoalTarget(modelData.value)
            }
        }
        Item { Layout.fillWidth: true }
    }

    Rectangle {
        Layout.fillWidth: true
        Layout.preferredHeight: 1
        color: app.theme.border
    }

    // Two-column metrics grid — Realized Profit has been promoted to the
    // hero above, so its grid slot is now "Year-End Forecast" (realized
    // plus remaining-days × avg-daily-profit), a genuinely new number.
    GridLayout {
        Layout.fillWidth: true
        columns: 2
        columnSpacing: 24
        rowSpacing: 4

        Metric {
            Layout.fillWidth: true
            label: "Unrealized Profit"
            value: account && account.goal ? (account.goal.unrealized || "—") : "—"
            sign:  account && account.goal && account.goal.unrealizedSign !== undefined
                   ? account.goal.unrealizedSign : 0
        }
        Metric {
            Layout.fillWidth: true
            label: "Year-End Forecast"
            value: account && account.goal ? (account.goal.yearEndForecast || "—") : "—"
            sign:  account && account.goal && account.goal.yearEndForecastSign !== undefined
                   ? account.goal.yearEndForecastSign : 0
        }
        Metric {
            Layout.fillWidth: true
            label: "Profit to Goal"
            value: account && account.goal ? (account.goal.remaining || "—") : "—"
            sign:  account && account.goal && account.goal.remainingSign !== undefined
                   ? account.goal.remainingSign : 0
        }
        Metric {
            Layout.fillWidth: true
            label: "Monthly Needed"
            value: account && account.goal ? (account.goal.monthly || "—") : "—"
        }
        Metric {
            Layout.fillWidth: true
            label: "Weekly Needed"
            value: account && account.goal ? (account.goal.weekly || "—") : "—"
        }
        Metric {
            Layout.fillWidth: true
            label: "Daily Needed"
            value: account && account.goal ? (account.goal.daily || "—") : "—"
        }
        Metric {
            Layout.fillWidth: true
            label: "Avg Daily"
            value: account && account.goal ? (account.goal.avgDaily || "—") : "—"
        }
        Metric {
            Layout.fillWidth: true
            label: "Catch-up Today"
            value: account && account.goal ? (account.goal.catchUp || "—") : "—"
        }
        Metric {
            Layout.fillWidth: true
            label: "Trading Days Elapsed"
            value: account && account.goal ? (account.goal.daysElapsed || "—") : "—"
        }
        Metric {
            Layout.fillWidth: true
            label: "Trading Days Remaining"
            value: account && account.goal ? (account.goal.daysRemaining || "—") : "—"
        }
    }
}
