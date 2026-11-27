import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtCharts
import "."

// Cumulative realized P/L over time, with the goal pace as a thin amber
// line (the same `pace` colour as the tick on the pace rail). The pace line
// only appears for "All time" / "Year to date", where it is comparable.
Card {
    id: root
    property var account: null

    readonly property var curve: account && account.equityCurve ? account.equityCurve : []
    readonly property var paceLine: account && account.equityPaceLine ? account.equityPaceLine : []
    readonly property bool isEmpty: curve.length === 0
    readonly property bool hasPace: paceLine.length === 2

    // Axis bounds cover both series so the pace line is never clipped.
    readonly property real xMin: isEmpty ? Date.now() : (hasPace ? Math.min(curve[0].x, paceLine[0].x) : curve[0].x)
    readonly property real xMax: isEmpty ? Date.now()
        : (hasPace ? Math.max(curve[curve.length - 1].x, paceLine[1].x) : curve[curve.length - 1].x)
    readonly property real yLo: isEmpty ? -100 : Math.min(account.equityCurveMinY, 0)
    readonly property real yHi: isEmpty ? 100 : Math.max(account.equityCurveMaxY, hasPace ? paceLine[1].y : 0)

    // ~4 "nice" gridline values (1/2/2.5/5 × 10^n) spanning [yLo, yHi].
    readonly property var yTicks: _niceTicks(yLo, yHi)
    function _niceTicks(lo, hi) {
        var raw = Math.max(1, hi - lo) / 4
        var mag = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10))
        var n = raw / mag
        var step = (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * mag
        var out = []
        for (var v = Math.floor(lo / step) * step; v <= Math.ceil(hi / step) * step + step / 2; v += step)
            out.push(Math.round(v * 100) / 100)
        return out.length > 1 ? out : [lo, lo + step]
    }
    function _axisMoney(v) {
        var s = Math.abs(v).toFixed(0).replace(/\B(?=(\d{3})+(?!\d))/g, ",")
        return (v < 0 ? "−$" : "$") + s
    }

    function _money(v) {
        var s = Math.abs(v).toFixed(0).replace(/\B(?=(\d{3})+(?!\d))/g, ",")
        return (v < 0 ? "−$" : v > 0 ? "+$" : "$") + s
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: 12
        SectionTitle {
            title: "Equity curve"
        }
        Item { Layout.fillWidth: true }
        // Inline legend: says what the two lines are without a chart legend box.
        Row {
            visible: !root.isEmpty
            spacing: 6
            Rectangle { width: 14; height: 2; radius: 1; color: app.theme.primary; anchors.verticalCenter: parent.verticalCenter }
            Label { text: "Realized"; color: app.theme.textMuted; font.pixelSize: 12 * app.theme.fontScale }
        }
        Row {
            visible: root.hasPace
            spacing: 6
            Rectangle { width: 14; height: 2; radius: 1; color: app.theme.pace; anchors.verticalCenter: parent.verticalCenter }
            Label { text: "Goal pace"; color: app.theme.textMuted; font.pixelSize: 12 * app.theme.fontScale }
        }
        ThemedComboBox {
            id: modeCombo
            visible: !root.isEmpty
            Layout.preferredWidth: 104
            model: ["Per trade", "Daily"]
            property var keys: ["trades", "daily"]
            currentIndex: {
                if (!account) return 0
                var i = keys.indexOf(account.equityCurveMode || "trades")
                return i >= 0 ? i : 0
            }
            onActivated: function (index) {
                if (account) account.setEquityCurveMode(keys[index])
            }
            Accessible.name: "Curve resolution"
        }
    }

    Item {
        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.minimumHeight: 160

        ChartView {
            id: chart
            anchors.fill: parent
            // ChartView adds its own outer margin; pull it in to the card padding.
            anchors.margins: -8
            visible: !root.isEmpty
            antialiasing: true
            legend.visible: false
            backgroundColor: "transparent"
            plotAreaColor: "transparent"
            margins.top: 4
            margins.bottom: 0
            margins.left: 0
            margins.right: 4

            DateTimeAxis {
                id: xAxis
                format: "MMM d"
                labelsColor: app.theme.textMuted
                labelsFont.family: app.theme.fontFamily
                labelsFont.pixelSize: 12 * app.theme.fontScale
                gridVisible: false
                lineVisible: false
                tickCount: 5
                // Pinned explicitly: with no points DateTimeAxis falls back to epoch 0.
                min: new Date(root.xMin)
                max: new Date(root.xMax)
            }
            // CategoryAxis instead of ValueAxis so tick labels can be real
            // money ("$6,000", "−$500"); ValueAxis printf formats have no
            // thousands separator or minus sign control.
            CategoryAxis {
                id: yAxis
                labelsColor: app.theme.textMuted
                labelsFont.family: app.theme.fontFamily
                labelsFont.pixelSize: 12 * app.theme.fontScale
                labelsPosition: CategoryAxis.AxisLabelsPositionOnValue
                gridLineColor: app.theme.border
                lineVisible: false
                property var ticks: root.yTicks
                readonly property real eps: (ticks[1] - ticks[0]) * 0.001
                min: ticks[0] - eps
                max: ticks[ticks.length - 1]
                startValue: ticks[0] - eps
                onTicksChanged: rebuild()
                Component.onCompleted: rebuild()
                function rebuild() {
                    var old = categoriesLabels.slice()
                    for (var i = 0; i < old.length; i++) remove(old[i])
                    for (var j = 0; j < ticks.length; j++) append(root._axisMoney(ticks[j]), ticks[j])
                }
            }

            LineSeries {
                id: paceSeries
                axisX: xAxis
                axisY: yAxis
                width: 1.5
                color: app.theme.pace
                // Bound like `series` below: ChartView swallows Connections
                // children in some PySide6 builds, bindings always fire.
                property var pts: root.paceLine
                onPtsChanged: { clear(); for (var i = 0; i < pts.length; i++) append(pts[i].x, pts[i].y) }
                Component.onCompleted: ptsChanged()
            }

            LineSeries {
                id: series
                axisX: xAxis
                axisY: yAxis
                width: 2
                color: app.theme.primary
                onHovered: (point, state) => root._onSeriesHover(point, state)
                property var curvePoints: root.curve
                onCurvePointsChanged: repopulate()
                Component.onCompleted: repopulate()
                // LineSeries has no "replace all"; clear + append is the idiom.
                // Only runs when the curve itself changes (analyticsChanged),
                // not on every marks tick.
                function repopulate() {
                    series.clear()
                    for (var i = 0; i < curvePoints.length; i++)
                        series.append(curvePoints[i].x, curvePoints[i].y)
                }
            }
        }

        ColumnLayout {
            anchors.centerIn: parent
            width: Math.min(parent.width - 32, 360)
            visible: root.isEmpty && account && account.loaded
            spacing: 4
            Label {
                Layout.fillWidth: true
                text: "No closed trades in this range"
                color: app.theme.text
                font.pixelSize: 13 * app.theme.fontScale
                font.weight: Font.DemiBold
                horizontalAlignment: Text.AlignHCenter
            }
            Label {
                Layout.fillWidth: true
                text: "Close a position and your realized profit will be charted here."
                color: app.theme.textMuted
                font.pixelSize: 13 * app.theme.fontScale
                wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignHCenter
            }
        }

        // Hover readout, positioned beside the hovered point and clamped
        // inside the chart area.
        Rectangle {
            id: tooltip
            visible: root._tipVisible && !root.isEmpty
            width: tipCol.implicitWidth + 16
            height: tipCol.implicitHeight + 10
            x: Math.max(0, Math.min(parent.width - width, root._tipX + 12))
            y: Math.max(0, Math.min(parent.height - height, root._tipY - height - 8))
            color: app.theme.card
            border.color: app.theme.border
            border.width: 1
            radius: 6

            Column {
                id: tipCol
                anchors.centerIn: parent
                Label {
                    text: root._tipDate
                    color: app.theme.textMuted
                    font.pixelSize: 12 * app.theme.fontScale
                }
                Label {
                    text: root._tipValue
                    color: app.theme.text
                    font.pixelSize: 13 * app.theme.fontScale
                    font.weight: Font.DemiBold
                }
            }
        }
    }

    property bool _tipVisible: false
    property real _tipX: 0
    property real _tipY: 0
    property string _tipDate: ""
    property string _tipValue: ""

    function _onSeriesHover(point, state) {
        if (!state || !chart) {
            root._tipVisible = false
            return
        }
        var pt = chart.mapToPosition(point, series)
        root._tipX = pt.x + chart.x
        root._tipY = pt.y + chart.y
        var d = new Date(point.x)
        var months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        root._tipDate = months[d.getMonth()] + " " + d.getDate() + ", " + d.getFullYear()
        root._tipValue = root._money(point.y) + " realized"
        root._tipVisible = true
    }
}
