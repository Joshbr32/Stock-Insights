import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "."

// Trading performance for the selected date range (and tag), read like a
// statement: one label/value per row, hairline between groups.
// The range set here also filters Trade history (state lives on the
// AccountController, so each account keeps its own range).
Card {
    id: root
    property var account: null
    spacing: 10

    function metric(key) {
        return account && account.analytics ? (account.analytics[key] || "—") : "—"
    }
    function metricSign(key) {
        return account && account.analytics && account.analytics[key + "Sign"] !== undefined
            ? account.analytics[key + "Sign"] : 0
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: 8
        SectionTitle {
            title: "Performance"
        }
        Item { Layout.fillWidth: true }
        // Only shown once the user has tagged at least one trade.
        ThemedComboBox {
            id: tagCombo
            visible: account && account.availableTags && account.availableTags.length > 0
            Layout.preferredWidth: 112
            model: ["All tags"].concat((account && account.availableTags) ? account.availableTags : [])
            currentIndex: {
                if (!account) return 0
                var t = account.tagFilter || ""
                if (!t) return 0
                var i = (account.availableTags || []).indexOf(t)
                return i >= 0 ? i + 1 : 0
            }
            onActivated: function (index) {
                if (!account) return
                var tags = account.availableTags || []
                account.setTagFilter(index === 0 ? "" : tags[index - 1])
            }
            Accessible.name: "Strategy tag"
        }
        ThemedComboBox {
            id: rangeCombo
            Layout.preferredWidth: 124
            model: ["All time", "This week", "This month", "Last 30 days", "Year to date"]
            property var keys: ["all", "week", "month", "30d", "ytd"]
            currentIndex: {
                if (!account) return 0
                var i = keys.indexOf(account.dateRangeKey || "all")
                return i >= 0 ? i : 0
            }
            onActivated: function (index) {
                if (account) account.setDateRange(keys[index])
            }
            Accessible.name: "Date range"
        }
    }

    // Groups: results, trade quality, risk. Rendered as a single column so
    // long labels never truncate at narrow widths.
    Repeater {
        model: [
            { group: [
                ["Projected yearly profit", "estYearly"],
                ["Avg daily profit", "avgDailyReturn"],
                ["Avg profit per trade", "avgProfit"],
                ["Avg return per trade", "avgRoi"] ] },
            { group: [
                ["Win rate", "winRate"],
                ["Profit factor", "profitFactor"],
                ["Avg win", "avgWin"],
                ["Avg loss", "avgLoss"],
                ["Best trade", "bestTrade"],
                ["Worst trade", "worstTrade"] ] },
            { group: [
                ["Largest drawdown", "maxDrawdown"],
                ["Current drawdown", "currentDrawdown"],
                ["Closed trades", "closedTrades"],
                ["Open trades", "openTrades"] ] }
        ]
        delegate: ColumnLayout {
            Layout.fillWidth: true
            spacing: 6
            Rectangle {
                visible: index > 0
                Layout.fillWidth: true
                Layout.preferredHeight: 1
                Layout.bottomMargin: 4
                color: app.theme.border
            }
            Repeater {
                model: modelData.group
                Metric {
                    Layout.fillWidth: true
                    label: modelData[0]
                    value: root.metric(modelData[1])
                    sign: root.metricSign(modelData[1])
                }
            }
        }
    }

    Item { Layout.fillHeight: true }
}
