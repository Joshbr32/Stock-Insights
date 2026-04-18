import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

Card {
    id: root
    property var account: null
    padding: 16

    SectionTitle {
        title: "Goal Dashboard"
        subtitle: account ? account.name : ""
    }

    // Annual target row + preset pills
    RowLayout {
        Layout.fillWidth: true
        spacing: 10

        Label {
            text: "Annual Target"
            color: app.theme.textMuted
            font.pointSize: 9
        }
        Label {
            text: account && account.goal ? (account.goal.target || "—") : "—"
            color: app.theme.text
            font.pointSize: 16
            font.weight: Font.Bold
        }
        Item { Layout.fillWidth: true }

        Repeater {
            model: account ? account.presets : []
            Pill {
                label: modelData.label
                selected: account && Math.abs(modelData.value - account.goalTargetValue) < 0.5
                onClicked: app.setGoalTarget(modelData.value)
            }
        }
    }

    Rectangle {
        Layout.fillWidth: true
        height: 1
        color: app.theme.border
    }

    // Two-column metrics grid
    GridLayout {
        Layout.fillWidth: true
        columns: 2
        columnSpacing: 24
        rowSpacing: 4

        Metric {
            Layout.fillWidth: true
            label: "Realized Profit"
            value: account && account.goal ? (account.goal.realized || "—") : "—"
        }
        Metric {
            Layout.fillWidth: true
            label: "Unrealized Profit"
            value: account && account.goal ? (account.goal.unrealized || "—") : "—"
        }
        Metric {
            Layout.fillWidth: true
            label: "Profit to Goal"
            value: account && account.goal ? (account.goal.remaining || "—") : "—"
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
