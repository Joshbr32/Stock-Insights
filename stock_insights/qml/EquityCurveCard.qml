import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtCharts
import "."

// Cumulative-realized-P/L curve over time. Re-renders whenever the
// account's date range changes or new closed trades come in.
Card {
    id: root
    property var account: null
    padding: 16

    // Helper — true when there's no closed trade yet to plot.
    readonly property bool isEmpty: !account || !account.equityCurve
                                     || account.equityCurve.length === 0

    SectionTitle {
        title: "Equity Curve"
        subtitle: account && account.equityCurve && account.equityCurve.length > 0
            ? "cumulative realized P/L  •   " + (account.equityCurve.length - 1)
                + (account.equityCurve.length === 2 ? " trade" : " trades")
            : ""
    }

    Rectangle {
        Layout.fillWidth: true
        Layout.preferredHeight: 1
        color: app.theme.border
    }

    // Wrapper for the chart so we can drop in an empty-state label that
    // shares the same geometry. ChartView renders fine down to ~120 px;
    // below that the axis labels start to overlap. 120 keeps the curve
    // legible at the documented minimum window size while leaving room
    // for the Card's SectionTitle + divider + padding above it.
    Rectangle {
        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.minimumHeight: 120
        color: "transparent"
        clip: true

        ChartView {
            id: chart
            anchors.fill: parent
            visible: !root.isEmpty
            antialiasing: true
            legend.visible: false
            backgroundColor: "transparent"
            // Title bar is provided by SectionTitle above — drop ChartView's
            // own to recover ~30 px of vertical space.
            titleColor: app.theme.text
            margins.top: 4
            margins.bottom: 4
            margins.left: 4
            margins.right: 4
            plotAreaColor: "transparent"
            // Use the theme's text color for axis text so it stays readable
            // on every theme. Grid lines + plot border lean on cardAlt for
            // a subtle off-card frame.

            DateTimeAxis {
                id: xAxis
                format: "MMM d"
                labelsColor: app.theme.textMuted
                labelsFont.pointSize: 8 * app.theme.fontScale
                gridLineColor: app.theme.cardAlt
                lineVisible: false
                tickCount: 6
                // Pin min/max explicitly to the curve's date range.
                // Without these, DateTimeAxis falls back to epoch 0
                // (1970-01-01 UTC, which renders as "Dec 31" in
                // negative-offset timezones — see screenshot bug) when
                // the LineSeries momentarily has no points.
                min: {
                    if (root.isEmpty) return new Date()
                    return new Date(account.equityCurve[0].x)
                }
                max: {
                    if (root.isEmpty) return new Date()
                    var pts = account.equityCurve
                    return new Date(pts[pts.length - 1].x)
                }
            }
            ValueAxis {
                id: yAxis
                labelsColor: app.theme.textMuted
                labelsFont.pointSize: 8 * app.theme.fontScale
                gridLineColor: app.theme.cardAlt
                lineVisible: false
                labelFormat: "$ %.0f"
                // Pad min/max by 5% so the line never touches the top/bottom
                // edge. Falls back to (-100, 100) when there's no data so the
                // axis doesn't collapse to a single tick.
                min: {
                    if (root.isEmpty) return -100
                    var lo = account.equityCurveMinY
                    var hi = account.equityCurveMaxY
                    var span = Math.max(1, Math.abs(hi - lo))
                    return lo - span * 0.08
                }
                max: {
                    if (root.isEmpty) return 100
                    var lo = account.equityCurveMinY
                    var hi = account.equityCurveMaxY
                    var span = Math.max(1, Math.abs(hi - lo))
                    return hi + span * 0.08
                }
            }

            LineSeries {
                id: series
                axisX: xAxis
                axisY: yAxis
                width: 2
                color: app.theme.primary
                // Bind the series content to the account's equity curve
                // via a property binding rather than Connections.
                //
                // The previous Connections approach failed silently:
                // ChartView's custom child management appears to swallow
                // non-series children (Connections, Timer, etc.) in some
                // Qt 6 / PySide6 builds, so the onMetricsChanged handler
                // never fired and the series stayed empty even though
                // `account.equityCurve` had data. Property bindings, by
                // contrast, are tracked by the QML engine directly: when
                // the notify signal (metricsChanged) fires, the binding
                // is invalidated and `onCurvePointsChanged` runs.
                property var curvePoints: (root.account && root.account.equityCurve)
                    ? root.account.equityCurve : []
                onCurvePointsChanged: repopulate()
                Component.onCompleted: repopulate()
                // LineSeries doesn't expose "replace all" — clear then
                // re-append is the canonical refresh idiom.
                function repopulate() {
                    series.clear()
                    for (var i = 0; i < curvePoints.length; i++) {
                        series.append(curvePoints[i].x, curvePoints[i].y)
                    }
                }
            }
        }

        // Empty state — shown only after data has been loaded once, so it
        // doesn't flash during the brief gap between QML mount and the
        // first refresh_all_accounts() call.
        Label {
            anchors.centerIn: parent
            visible: root.isEmpty && account && account.loaded
            text: "No closed trades yet — close a trade to see the curve"
            color: app.theme.textMuted
            font.pointSize: 10 * app.theme.fontScale
        }
    }
}
