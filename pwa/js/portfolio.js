// portfolio.js — JS port of the compute functions from portfolio.py.
//
// We do all derivation client-side: the server only stores raw trades. That
// keeps the API tiny and means the desktop & mobile clients can't drift
// out of sync mathematically (this file mirrors portfolio.py 1:1 for the
// numbers that appear in both UIs).

// ── Trade helpers ──────────────────────────────────────────────────────

/** Normalize raw /trades response rows into a uniform shape. */
export function normalizeTrade(t) {
    return {
        id: t.id,
        account: t.account || "",
        instrument: (t.instrument || "").trim().toUpperCase(),
        share_count: Number(t.share_count) || 0,
        buy_price: Number(t.buy_price) || 0,
        sell_price: t.sell_price === null || t.sell_price === undefined
            ? null : Number(t.sell_price),
        open_date: t.open_date || null,
        close_date: t.close_date || null,
        notes: t.notes || "",
        is_pending: !!t.is_pending,
        is_short: !!t.is_short,
    };
}

export function isClosed(t) {
    return t.sell_price !== null && t.sell_price !== undefined && !!t.close_date;
}

export function tradeStatus(t) {
    if (t.is_pending) return "WAITING";
    if (t.is_short) return isClosed(t) ? "COVERED" : "SHORT";
    return isClosed(t) ? "CLOSED" : "OPEN";
}

export function tradeProfit(t) {
    if (!isClosed(t) || t.sell_price === null) return null;
    if (t.is_short) {
        return (Number(t.buy_price) - Number(t.sell_price)) * Number(t.share_count);
    }
    return (Number(t.sell_price) - Number(t.buy_price)) * Number(t.share_count);
}

export function costBasis(t) {
    return Number(t.buy_price) * Number(t.share_count);
}

// ── Holdings (open positions only, grouped by symbol & long/short) ─────

export function computeHoldings(trades) {
    const groups = new Map();
    for (const t of trades) {
        if (isClosed(t) || t.is_pending) continue;
        if (!t.instrument || t.share_count <= 0) continue;
        const key = (t.is_short ? `${t.instrument}:SHORT` : t.instrument);
        const g = groups.get(key) || {
            instrument: t.instrument, qty: 0, cost: 0, is_short: t.is_short, notes: [],
        };
        g.qty += t.share_count;
        g.cost += t.buy_price * t.share_count;
        if (t.notes) g.notes.push(t.notes);
        groups.set(key, g);
    }
    const out = [];
    for (const g of groups.values()) {
        if (g.qty <= 0) continue;
        out.push({
            instrument: g.instrument,
            qty: g.is_short ? -g.qty : g.qty,
            avg_cost: g.cost / g.qty,
            notes: g.notes.filter(Boolean).join(" | "),
        });
    }
    // Longs first, then shorts, alphabetical within each group.
    return out.sort((a, b) =>
        (a.qty < 0) - (b.qty < 0) || a.instrument.localeCompare(b.instrument)
    );
}

export function realizedBySymbol(trades) {
    const out = {};
    for (const t of trades) {
        if (!isClosed(t) || t.is_pending) continue;
        out[t.instrument] = (out[t.instrument] || 0) + (tradeProfit(t) || 0);
    }
    return out;
}

// ── Portfolio view rows + summary ──────────────────────────────────────

export function computePortfolio(holdings, marks, realizedMap = {}) {
    let totalMV = 0;
    let grossMV = 0;
    let grossCost = 0;

    const staged = holdings.map(h => {
        const mark = marks[h.instrument];
        const cb = h.qty * h.avg_cost;
        const mv = mark != null ? mark * h.qty : 0;
        const upl = mark != null ? mv - cb : 0;
        totalMV += mv;
        grossMV += Math.abs(mv);
        grossCost += Math.abs(cb);
        return {h, mark, mv, upl, rpl: realizedMap[h.instrument] || 0};
    });

    let totalUpl = 0;
    const rows = staged.map(({h, mark, mv, upl, rpl}) => {
        totalUpl += upl;
        return {
            instrument: h.instrument,
            qty: h.qty,
            avg_cost: h.avg_cost,
            mark,
            market_value: mv,
            weight_pct: grossMV > 0 ? (Math.abs(mv) / grossMV) * 100 : 0,
            unrealized_pl: upl,
            realized_pl: rpl,
            total_pl: rpl + upl,
            notes: h.notes,
        };
    });

    const allRealized = Object.values(realizedMap).reduce((a, b) => a + b, 0);
    const summary = {
        market_value: totalMV,
        cost_basis: grossCost,
        unrealized_pl: totalUpl,
        realized_pl: allRealized,
        total_pl: allRealized + totalUpl,
        positions: rows.length,
        return_pct: grossCost > 0 ? ((allRealized + totalUpl) / grossCost) * 100 : null,
    };
    return {rows, summary};
}

// ── Goal progress ─────────────────────────────────────────────────────

/** Trading-day count (NYSE-ish): weekdays only. The Python side uses
 *  pandas-market-calendars when available, but the mobile UI only needs
 *  rough cadence numbers, so weekday counting is plenty close. */
function tradingDaysBetween(start, end) {
    if (!start || !end || end < start) return 0;
    let count = 0;
    const cur = new Date(start);
    while (cur <= end) {
        const d = cur.getDay();
        if (d !== 0 && d !== 6) count++;
        cur.setDate(cur.getDate() + 1);
    }
    return count;
}

function tradingDaysElapsedYTD(today = new Date()) {
    return tradingDaysBetween(new Date(today.getFullYear(), 0, 1), today);
}

function tradingDaysRemainingThisYear(today = new Date()) {
    return tradingDaysBetween(today, new Date(today.getFullYear(), 11, 31));
}

export function computeGoalProgress(trades, target, today = new Date()) {
    let realized = 0;
    for (const t of trades) {
        if (!isClosed(t) || t.is_pending) continue;
        realized += tradeProfit(t) || 0;
    }
    // Unrealized requires marks — we add it from the caller via computePortfolio
    // and pass total_pl back through. To keep this function pure we report
    // realized only; the Goals view augments with unrealized separately.

    const elapsed = tradingDaysElapsedYTD(today);
    const remaining = tradingDaysRemainingThisYear(today);
    const remainingProfit = Math.max(0, target - realized);

    const monthsLeft = Math.max(1, 12 - today.getMonth());
    const weeksLeft = Math.max(1, Math.ceil(remaining / 5));
    const daysLeft = Math.max(1, remaining);

    const avgDaily = elapsed > 0 ? realized / elapsed : null;

    return {
        target,
        realized,
        remaining_profit: remainingProfit,
        monthly_to_goal: remainingProfit / monthsLeft,
        weekly_to_goal: remainingProfit / weeksLeft,
        daily_to_goal: remainingProfit / daysLeft,
        avg_daily: avgDaily,
        days_elapsed: elapsed,
        days_remaining: remaining,
    };
}

// ── Date-range filtering ───────────────────────────────────────────────
//
// Mirrors AccountController._date_filtered_with_orig_index in
// qml_bridge.py — the desktop's date-range combo and the mobile's
// range picker MUST use identical semantics so the same data window
// produces the same metrics on both clients.
//
// "Date" for filtering = close_date if closed, else open_date. Pending
// trades (no fill date yet) always pass through — hiding them would
// mask what the user is waiting on.

/** Parse a YYYY-MM-DD string into a Date in local time. Returns null
 *  for empty/invalid input so callers can decide how to handle it. */
function parseISODate(s) {
    if (!s) return null;
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
    if (!m) return null;
    return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
}

/** Returns true iff `t` falls inside the date range identified by `key`.
 *  Valid keys: "all" | "week" | "month" | "30d" | "ytd". Unknown keys
 *  fall back to "all" so a stale State.dateRangeKey can't strand the UI. */
export function tradeInRange(t, key, today = new Date()) {
    if (key === "all" || !key) return true;
    if (t.is_pending) return true;
    const ref = parseISODate(isClosed(t) ? t.close_date : t.open_date);
    if (!ref) return true;  // ill-formed dates pass through, same as Python

    const t0 = new Date(today.getFullYear(), today.getMonth(), today.getDate());
    let cutoff;
    if (key === "week") {
        // Start of this week (Sunday-based, matching Python's calendar.weekday()
        // semantics inverted — pandas uses Monday-start; the desktop's filter
        // uses the start of the current ISO week. Sunday-start is close
        // enough for human "this week" intuition on mobile.)
        const dow = t0.getDay();  // 0=Sun
        cutoff = new Date(t0);
        cutoff.setDate(t0.getDate() - dow);
    } else if (key === "month") {
        cutoff = new Date(t0.getFullYear(), t0.getMonth(), 1);
    } else if (key === "30d") {
        cutoff = new Date(t0);
        cutoff.setDate(t0.getDate() - 30);
    } else if (key === "ytd") {
        cutoff = new Date(t0.getFullYear(), 0, 1);
    } else {
        return true;
    }
    return ref >= cutoff;
}

/** Filter a trade list by date-range key. */
export function filterTradesByDateRange(trades, key, today = new Date()) {
    if (!key || key === "all") return trades;
    return trades.filter(t => tradeInRange(t, key, today));
}

// ── Equity curve ───────────────────────────────────────────────────────
//
// Mirrors AccountController._build_equity_curve in qml_bridge.py.
// Returns an array of {x, y} where x is an epoch-ms timestamp and y is
// the running cumulative realized P/L after that trade closed. The
// series is seeded with a zero point one day before the first close so
// the line visually rises from the x-axis rather than starting
// mid-air.

export function buildEquityCurve(trades) {
    const closed = trades.filter(
        t => isClosed(t) && !t.is_pending && t.close_date && tradeProfit(t) != null
    );
    if (closed.length === 0) return [];
    // Stable sort by close_date so cumulative addition makes sense.
    closed.sort((a, b) => (a.close_date < b.close_date ? -1
        : a.close_date > b.close_date ? 1 : 0));

    const firstClose = parseISODate(closed[0].close_date);
    const seed = new Date(firstClose);
    seed.setDate(seed.getDate() - 1);
    const pts = [{x: seed.getTime(), y: 0}];

    let running = 0;
    for (const t of closed) {
        running += tradeProfit(t) || 0;
        // 16:00 (= NYSE close-of-day) on close_date so the line lands
        // at end-of-trading on the relevant day, matching the desktop.
        const d = parseISODate(t.close_date);
        d.setHours(16, 0, 0, 0);
        pts.push({x: d.getTime(), y: running});
    }
    return pts;
}

// ── Trade analytics (closed-trade quality stats) ───────────────────────

export function computeAnalytics(trades) {
    const closed = trades.filter(t => isClosed(t) && !t.is_pending);
    const open = trades.filter(t => !isClosed(t) && !t.is_pending);

    const profits = closed.map(tradeProfit);
    const realized = profits.reduce((a, b) => a + (b || 0), 0);
    const wins = profits.filter(p => p > 0);
    const losses = profits.filter(p => p < 0);
    const sumLosses = Math.abs(losses.reduce((a, b) => a + b, 0));

    return {
        realized_profit: realized,
        closed_trades: closed.length,
        open_trades: open.length,
        avg_profit_per_trade: closed.length ? realized / closed.length : null,
        win_rate_pct: closed.length ? (wins.length / closed.length) * 100 : null,
        avg_win: wins.length ? wins.reduce((a, b) => a + b, 0) / wins.length : null,
        avg_loss: losses.length ? losses.reduce((a, b) => a + b, 0) / losses.length : null,
        best_trade: profits.length ? Math.max(...profits) : null,
        worst_trade: profits.length ? Math.min(...profits) : null,
        profit_factor: sumLosses > 0
            ? wins.reduce((a, b) => a + b, 0) / sumLosses
            : (wins.length ? Infinity : null),
    };
}
