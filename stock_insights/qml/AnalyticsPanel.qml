import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

Card {
    id: root
    property var account: null
    padding: 16

    // Helper — read a metric value or sign from the account's analytics
    // map without throwing if account is still null at first paint.
    function metric(key) {
        return account && account.analytics ? (account.analytics[key] || "—") : "—"
    }
    function metricSign(key) {
        return account && account.analytics && account.analytics[key + "Sign"] !== undefined
            ? account.analytics[key + "Sign"] : 0
    }

    SectionTitle { title: "Performance Analytics" }

    Rectangle {
        Layout.fillWidth: true
        Layout.preferredHeight: 1
        color: app.theme.border
    }

    // Two-column metric grid — same shape as the goal dashboard so the
    // two cards visually rhyme.
    GridLayout {
        Layout.fillWidth: true
        columns: 2
        columnSpacing: 24
        rowSpacing: 4

        // Row 1 — counts
        Metric { Layout.fillWidth: true; label: "Open Trades";        value: metric("openTrades") }
        Metric { Layout.fillWidth: true; label: "Closed Trades";      value: metric("closedTrades") }

        // Row 2 — quality summary
        Metric { Layout.fillWidth: true; label: "Win Rate";           value: metric("winRate");
                 sign: metricSign("winRate") }
        Metric { Layout.fillWidth: true; label: "Profit Factor";      value: metric("profitFactor");
                 sign: metricSign("profitFactor") }

        // Row 3 — average per trade vs. winners-only / losers-only
        Metric { Layout.fillWidth: true; label: "Avg Profit / Trade"; value: metric("avgProfit");
                 sign: metricSign("avgProfit") }
        Metric { Layout.fillWidth: true; label: "Avg Trade Value";    value: metric("avgTradeValue") }

        // Row 4
        Metric { Layout.fillWidth: true; label: "Avg Win";            value: metric("avgWin");
                 sign: metricSign("avgWin") }
        Metric { Layout.fillWidth: true; label: "Avg Loss";           value: metric("avgLoss");
                 sign: metricSign("avgLoss") }

        // Row 5 — extremes
        Metric { Layout.fillWidth: true; label: "Best Trade";         value: metric("bestTrade");
                 sign: metricSign("bestTrade") }
        Metric { Layout.fillWidth: true; label: "Worst Trade";        value: metric("worstTrade");
                 sign: metricSign("worstTrade") }

        // Row 6 — return rate + forecast
        Metric { Layout.fillWidth: true; label: "Avg ROI %";          value: metric("avgRoi");
                 sign: metricSign("avgRoi") }
        Metric { Layout.fillWidth: true; label: "Avg Daily Return";   value: metric("avgDailyReturn");
                 sign: metricSign("avgDailyReturn") }

        // Row 7 — full-pace projection (the marquee number)
        Metric { Layout.fillWidth: true; label: "Est. Yearly Profit"; value: metric("estYearly");
                 sign: metricSign("estYearly") }
        Item   { Layout.fillWidth: true }   // visual balance
    }
}
