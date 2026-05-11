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

    // Header — title on the left + resampling toggle on the right.
    // The toggle stays out of the way (small, low-contrast text) but
    // is always reachable: dense histories with 100+ trades benefit
    // hugely from daily bucketing, while a fresh account is more
    // readable per-trade.
    RowLayout {
        Layout.fillWidth: true
        spacing: 8
        SectionTitle {
            title: "Equity Curve"
            Layout.fillWidth: true
            subtitle: account && account.equityCurve && account.equityCurve.length > 0
                ? "cumulative realized P/L  •   " + (account.equityCurve.length - 1)
                    + (account.equityCurve.length === 2 ? " trade" : " trades")
                : ""
        }
        // Per-trade / Daily switcher — bound to AccountController.equityCurveMode.
        // Hidden when the curve is empty; nothing to resample yet.
        ThemedComboBox {
            id: modeCombo
            visible: !root.isEmpty
            Layout.preferredWidth: 100
            Layout.preferredHeight: 26
            font.pointSize: 8 * app.theme.fontScale
            model: ["Per trade", "Daily"]
            property var keys: ["trades", "daily"]
            currentIndex: {
                if (!account) return 0
                var i = keys.indexOf(account.equityCurveMode || "trades")
                return i >= 0 ? i : 0
            }
            onActivated: function(index) {
                if (account) account.setEquityCurveMode(keys[index])
            }
        }
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
                // Emit hovered signals so the floating tooltip below
                // can show the date + cumulative value at the hovered
                // point. `pointsVisible: true` would also draw a marker
                // dot on every point but tends to crowd the chart on
                // dense histories — we rely on the moving tooltip
                // instead.
                onHovered: (point, state) => root._onSeriesHover(point, state)
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

        // ── Floating hover tooltip ────────────────────────────────────
        // Driven by LineSeries.onHovered (state=true on enter, false on
        // exit). Positioned just above-and-right of the cursor; clamps
        // to the wrapper so it never overflows the card edge.
        Rectangle {
            id: tooltip
            visible: root._tipVisible && !root.isEmpty
            // Resize to fit the label automatically, plus a 6 px margin
            // each side and 4 px top/bottom — feels right at 8–9 pt text.
            width: tipLabel.implicitWidth + 12
            height: tipLabel.implicitHeight + 8
            x: Math.max(0, Math.min(parent.width - width,  root._tipX + 12))
            y: Math.max(0, Math.min(parent.height - height, root._tipY - height - 8))
            color: app.theme.cardAlt
            border.color: app.theme.border
            border.width: 1
            radius: 4
            antialiasing: true

            Label {
                id: tipLabel
                anchors.centerIn: parent
                text: root._tipText
                color: app.theme.text
                font.pointSize: 8 * app.theme.fontScale
            }
        }
    }

    // ── Tooltip state ────────────────────────────────────────────────
    // Backing properties for the floating hover tooltip. Kept on the
    // root (Card) so they survive ChartView's child-rebuild cycles and
    // can be bound from the LineSeries hover callback below.
    property bool _tipVisible: false
    property real _tipX: 0
    property real _tipY: 0
    property string _tipText: ""

    // Hover handler — receives plot-area coordinates from LineSeries.
    // Translates the data-space point into pixel coordinates relative
    // to the chart wrapper, then formats a short "MMM d · $1,234" line
    // matching the axis labels.
    function _onSeriesHover(point, state) {
        if (!state || !chart) {
            root._tipVisible = false
            return
        }
        // mapToPosition returns a point in chart's local coordinates.
        // Since chart anchors.fill the wrapper, those coordinates are
        // already what the tooltip wants — no further translation needed.
        var pt = chart.mapToPosition(point, series)
        root._tipX = pt.x
        root._tipY = pt.y
        // point.x is ms-since-epoch (DateTimeAxis); format same as axis.
        var d = new Date(point.x)
        var months = ["Jan","Feb","Mar","Apr","May","Jun",
                      "Jul","Aug","Sep","Oct","Nov","Dec"]
        var dollars = (point.y >= 0 ? "+$" : "-$")
                       + Math.abs(point.y).toFixed(0).replace(
                              /\B(?=(\d{3})+(?!\d))/g, ",")
        root._tipText = months[d.getMonth()] + " " + d.getDate()
                       + "  ·  " + dollars
        root._tipVisible = true
    }
}
