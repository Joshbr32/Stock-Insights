// charts.js — the pace rail (home hero) and the equity-curve chart.
//
// Both are hand-built DOM/SVG (no chart library) so the PWA stays small
// and works offline. Colours come from CSS custom properties in
// styles.css; amber (`--pace`) appears only on the pace tick and the
// equity curve's pace line, as the Harbor design system requires.
//
// Pace maths mirrors the desktop pace rail
// (qml_bridge.AccountController._pace_map / _build_pace_line); the
// trading-day arithmetic itself lives in portfolio.js.

import {goalExpectedByNow, tradingDaysBetween} from "./portfolio.js";
import {el, fmtShortDate, money, plural, reducedMotion, signedMoney, svg} from "./ui.js";

// ── Pace maths ────────────────────────────────────────────────────────

/** Weekdays in [start, end], inclusive. Kept as an export for callers;
 *  same function as portfolio.js's tradingDaysBetween(). */
export const weekdaysBetween = tradingDaysBetween;

/** Fraction (0..1) of this year's goal that should be realised by `date`:
 *  elapsed / (elapsed + remaining) trading days, today counted in both,
 *  exactly as compute_goal_progress does. */
export function paceFraction(date, year = new Date().getFullYear()) {
    const jan1 = new Date(year, 0, 1), dec31 = new Date(year, 11, 31);
    if (date < jan1) return 0;
    if (date > dec31) return 1;
    return goalExpectedByNow(1, date);
}

/** Where realised P/L should be today to hit `target` by Dec 31. */
export const paceToday = (target, today = new Date()) => goalExpectedByNow(target, today);

/** Pace status line, worded like the desktop rail: "Goal reached",
 *  "$1,240 ahead of pace" (also when exactly on pace), "$860 behind pace",
 *  or "Close a trade to start your pace" before the first close. */
export function paceSentence(realized, target, pace, hasClosed = true) {
    if (!hasClosed) return "Close a trade to start your pace";
    if (realized >= target) return "Goal reached";
    const diff = realized - pace;
    return `${money(Math.abs(diff), {whole: true})} ${diff >= 0 ? "ahead of" : "behind"} pace`;
}

// ── Pace rail ─────────────────────────────────────────────────────────
//
//  Goal $10,000 by Dec 31                       $1,240 ahead of pace
//  +$4,860
//  |==================●=======|-----------------------------|
//  $0                today's pace $3,620               $10,000
//
// opts: {title, target, realized, hasClosed?, today?, compact?, animate?}
// `hasClosed` false shows the neutral "start" state (a new account is not
// "behind"). `animate` runs the 400 ms fill once (the caller decides when:
// first load of an account); it is skipped under prefers-reduced-motion.
export function paceRail({title, target, realized, hasClosed = true, today = new Date(), compact = false, animate = false}) {
    const pace = paceToday(target, today);
    const clamp = v => Math.max(0, Math.min(100, v));
    const fillPct = target > 0 ? clamp((realized / target) * 100) : 0;
    const pacePct = target > 0 ? clamp((pace / target) * 100) : 0;
    const status = paceSentence(realized, target, pace, hasClosed);
    const statusClass = !hasClosed ? "" : realized >= pace ? " is-ahead" : " is-behind";

    const fill = el("div", {class: "pace-fill"});
    const dot = el("div", {class: "pace-dot"});
    const setFill = p => {
        fill.style.width = `${p}%`;
        dot.style.left = `${p}%`;
    };
    if (animate && !reducedMotion()) {
        setFill(0);
        // Two frames: the first commits width 0, the second starts the transition.
        requestAnimationFrame(() => requestAnimationFrame(() => setFill(fillPct)));
    } else {
        setFill(fillPct);
    }

    // The pace label sits under the tick but is clamped so it never runs
    // off either end of the track on a narrow phone.
    const anchor = pacePct < 25 ? "is-start" : pacePct > 75 ? "is-end" : "";
    const paceLabel = el("span", {class: "pace-label-tick " + anchor},
        `Today's pace ${money(pace, {whole: true})}`);
    paceLabel.style.setProperty("--at", `${pacePct}%`);
    const tick = el("div", {class: "pace-tick"});
    tick.style.left = `${pacePct}%`;

    const summary = `${title}. Realised ${signedMoney(realized, {whole: true})} of `
        + `${money(target, {whole: true})}. Today's pace is ${money(pace, {whole: true})}. ${status}.`;

    return el("section", {class: "pace" + (compact ? " pace-compact" : "")}, [
        el("div", {class: "pace-head"}, [
            el("h2", {class: "pace-goal"}, title),
            el("p", {class: "pace-status" + statusClass}, status),
        ]),
        el("p", {class: "pace-value num"}, [
            signedMoney(realized, {whole: compact}),
            el("span", {class: "pace-value-label"}, " realised"),
        ]),
        el("div", {class: "pace-track", role: "img", "aria-label": summary}, [fill, tick, dot]),
        el("div", {class: "pace-scale", "aria-hidden": "true"}, [
            el("span", {class: "num"}, "$0"),
            paceLabel,
            el("span", {class: "num"}, money(target, {whole: true})),
        ]),
    ]);
}

// ── Equity curve ──────────────────────────────────────────────────────
//
// curve: [{x: epoch ms, y: cumulative realised P/L}] from buildEquityCurve.
// opts.paceTarget: when set, draws the amber pace line for this year's goal
//   (straight from $0 on Jan 1 to today's expected value, like the
//   desktop's _build_pace_line) and widens the x-axis to cover Jan 1 ..
//   today so "where you are vs where you should be" reads directly. Only pass it when the curve is all-time realised
//   P/L for the same trades the goal counts (otherwise they don't compare).
//
// The SVG uses a fixed viewBox stretched to the card (preserveAspectRatio
// none) with non-scaling strokes; dots and the tooltip are HTML overlays
// positioned in percentages so they stay round at any width.
export function equityChart(curve, {paceTarget = null} = {}) {
    const W = 320, H = 140, PADY = 10;
    const xs = curve.map(p => p.x), ys = curve.map(p => p.y);
    const first = xs[0];  // the $0 seed, one day before the first close

    // Pace line: two points, as on the desktop chart.
    const pacePts = [];
    if (paceTarget != null) {
        const now = new Date();
        const todayClose = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 16).getTime();
        pacePts.push({x: new Date(now.getFullYear(), 0, 1).getTime(), y: 0},
            {x: todayClose, y: paceToday(paceTarget, now)});
    }
    const xMin = pacePts.length ? Math.min(first, pacePts[0].x) : first;
    const xMax = pacePts.length ? Math.max(xs[xs.length - 1], pacePts[1].x) : xs[xs.length - 1];

    const allY = ys.concat(pacePts.map(p => p.y));
    const yMin = Math.min(0, ...allY), yMax = Math.max(0, ...allY);
    const ySpan = Math.max(1, yMax - yMin), xSpan = Math.max(1, xMax - xMin);
    const fx = x => (x - xMin) / xSpan;                  // 0..1
    const fy = y => (PADY + (1 - (y - yMin) / ySpan) * (H - 2 * PADY)) / H;  // 0..1, top = 0
    const pts = arr => arr.map(p => `${(fx(p.x) * W).toFixed(1)},${(fy(p.y) * H).toFixed(1)}`).join(" ");

    const children = [];
    if (yMin < 0 && yMax > 0) {
        const y0 = (fy(0) * H).toFixed(1);
        children.push(svg("line", {x1: 0, x2: W, y1: y0, y2: y0, class: "eq-zero"}));
    }
    if (pacePts.length) children.push(svg("polyline", {points: pts(pacePts), class: "eq-pace"}));
    children.push(svg("polyline", {points: pts(curve), class: "eq-line"}));

    const place = (node, p) => {
        node.style.left = `${fx(p.x) * 100}%`;
        node.style.top = `${fy(p.y) * 100}%`;
    };
    const last = curve[curve.length - 1];
    const endDot = el("div", {class: "eq-dot"});
    place(endDot, last);
    const marker = el("div", {class: "eq-dot eq-marker", hidden: true});
    const tip = el("div", {class: "eq-tip num", hidden: true});

    const trades = curve.length - 1;  // curve is seeded with a zero point
    const label = `Equity curve. Realised P/L ${signedMoney(last.y)} over ${plural(trades, "closed trade")}, `
        + `${fmtShortDate(first + 86400000)} to ${fmtShortDate(last.x)}.`
        + (pacePts.length ? " The dashed line is the pace needed to reach the goal." : "")
        + " Use the arrow keys to step through points.";

    const plot = el("div", {
        class: "eq-plot", tabindex: "0", role: "img", "aria-label": label,
    }, [svg("svg", {viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", "aria-hidden": "true"}, children),
        endDot, marker, tip]);

    // ── Inspect a point (pointer, touch or keyboard) ────────────────
    let idx = -1;
    function show(i) {
        idx = Math.max(0, Math.min(curve.length - 1, i));
        const p = curve[idx];
        place(marker, p);
        marker.hidden = false;
        tip.textContent = `${fmtShortDate(p.x)}  ${signedMoney(p.y)}`;
        tip.hidden = false;
        // Clamp the tooltip inside the plot.
        const w = plot.clientWidth, tw = tip.offsetWidth;
        const cx = fx(p.x) * w;
        tip.style.left = `${Math.max(0, Math.min(w - tw, cx - tw / 2))}px`;
        tip.style.top = `${Math.max(0, fy(p.y) * plot.clientHeight - 36)}px`;
    }
    function hide() {
        marker.hidden = true;
        tip.hidden = true;
    }
    function nearest(clientX) {
        const r = plot.getBoundingClientRect();
        const f = (clientX - r.left) / r.width;
        let best = 0, bestD = Infinity;
        for (let i = 0; i < curve.length; i++) {
            const d = Math.abs(fx(curve[i].x) - f);
            if (d < bestD) {
                bestD = d;
                best = i;
            }
        }
        return best;
    }
    plot.addEventListener("pointermove", e => show(nearest(e.clientX)));
    plot.addEventListener("pointerdown", e => show(nearest(e.clientX)));
    plot.addEventListener("pointerleave", e => {
        if (e.pointerType === "mouse") hide();
    });
    plot.addEventListener("pointercancel", hide);
    plot.addEventListener("blur", hide);
    plot.addEventListener("keydown", e => {
        const step = {ArrowLeft: -1, ArrowRight: 1}[e.key];
        if (step) show((idx < 0 ? curve.length : idx) + step);
        else if (e.key === "Home") show(0);
        else if (e.key === "End") show(curve.length - 1);
        else if (e.key === "Escape") hide();
        else return;
        e.preventDefault();
    });

    return el("div", {class: "eq"}, [
        plot,
        el("div", {class: "eq-axis", "aria-hidden": "true"}, [
            el("span", {}, fmtShortDate(xMin === first ? first + 86400000 : xMin)),
            pacePts.length ? el("span", {class: "eq-legend"}, [el("i", {class: "eq-legend-pace"}), "Pace"]) : null,
            el("span", {}, paceTarget != null ? "Today" : fmtShortDate(last.x)),
        ]),
    ]);
}
