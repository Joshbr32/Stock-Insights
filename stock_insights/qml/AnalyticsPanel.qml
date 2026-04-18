import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

Card {
    id: root
    property var account: null
    padding: 16

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

    GridLayout {
        Layout.fillWidth: true
        columns: 2
        columnSpacing: 24
        rowSpacing: 4

        Metric { Layout.fillWidth: true; label: "Open Trades";        value: metric("openTrades") }
        Metric { Layout.fillWidth: true; label: "Closed Trades";      value: metric("closedTrades") }

        Metric { Layout.fillWidth: true; label: "Win Rate";           value: metric("winRate");
                 sign: metricSign("winRate") }
        Metric { Layout.fillWidth: true; label: "Profit Factor";      value: metric("profitFactor");
                 sign: metricSign("profitFactor") }

        Metric { Layout.fillWidth: true; label: "Avg Profit / Trade"; value: metric("avgProfit");
                 sign: metricSign("avgProfit") }
        Metric { Layout.fillWidth: true; label: "Avg Trade Value";    value: metric("avgTradeValue") }

        Metric { Layout.fillWidth: true; label: "Avg Win";            value: metric("avgWin");
                 sign: metricSign("avgWin") }
        Metric { Layout.fillWidth: true; label: "Avg Loss";           value: metric("avgLoss");
                 sign: metricSign("avgLoss") }

        Metric { Layout.fillWidth: true; label: "Best Trade";         value: metric("bestTrade");
                 sign: metricSign("bestTrade") }
        Metric { Layout.fillWidth: true; label: "Worst Trade";        value: metric("worstTrade");
                 sign: metricSign("worstTrade") }

        Metric { Layout.fillWidth: true; label: "Avg ROI %";          value: metric("avgRoi");
                 sign: metricSign("avgRoi") }
        Metric { Layout.fillWidth: true; label: "Avg Daily Return";   value: metric("avgDailyReturn");
                 sign: metricSign("avgDailyReturn") }
    }

    // ── Est. Yearly Profit — featured "marquee" metric. Spans both
    // grid columns and lives in its own accent-colored container so the
    // headline projection stands out from the rest of the analytics.
    Rectangle {
        Layout.fillWidth: true
        Layout.topMargin: 4
        Layout.preferredHeight: 52
        radius: 10
        color: Qt.rgba(
            _hex_r(app.theme.primary),
            _hex_g(app.theme.primary),
            _hex_b(app.theme.primary),
            0.10            // subtle tint — same hue as primary, barely there
        )
        border.color: app.theme.primary
        border.width: 1

        // Small accent strip on the left — same idea as the SectionTitle bar.
        Rectangle {
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.topMargin: 8
            anchors.bottomMargin: 8
            width: 3
            radius: 1.5
            color: app.theme.primary
        }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 16
            anchors.rightMargin: 14
            spacing: 10

            ColumnLayout {
                spacing: 0
                Layout.alignment: Qt.AlignVCenter
                Layout.fillWidth: true
                Label {
                    text: "Est. Yearly Profit"
                    color: app.theme.textMuted
                    font.pointSize: 9
                    font.weight: Font.DemiBold
                }
                Label {
                    text: "at current pace × 252 trading days"
                    color: app.theme.textMuted
                    font.pointSize: 8
                    opacity: 0.75
                }
            }

            Label {
                text: metric("estYearly")
                color: metricSign("estYearly") < 0 ? app.theme.bad : app.theme.primary
                font.pointSize: 15
                font.weight: Font.Bold
                horizontalAlignment: Text.AlignRight
            }
        }
    }

    // Tiny hex→float helpers so Qt.rgba can produce a tinted background
    // from whatever color string the theme's `primary` property returns.
    function _hex_r(c) { return Number("0x" + String(c).slice(1, 3)) / 255 }
    function _hex_g(c) { return Number("0x" + String(c).slice(3, 5)) / 255 }
    function _hex_b(c) { return Number("0x" + String(c).slice(5, 7)) / 255 }
}
