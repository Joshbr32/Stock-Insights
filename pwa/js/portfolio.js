// portfolio.js — JS port of the trade math in stock_insights/portfolio.py.
//
// The server only stores raw trades; every number the phone shows is
// derived here. portfolio.py is the source of truth and this file mirrors
// it 1:1 (same filters, same order of summation, same null rules), so the
// phone and the desktop show the same numbers for the same trades. Change
// math or rounding in both files together; docs/code/pwa/js/portfolio.md
// describes how the two were checked against each other.
//
// Trading-day counts are weekdays only. portfolio.py uses the NYSE
// calendar only when the optional pandas_market_calendars package is
// installed; it is not in requirements.txt, so both sides count weekdays.

// ── Trade identity ─────────────────────────────────────────────────────

const UID_RE = /^[0-9a-f]{32}$/;

/** True for a valid trade uid: 32 lowercase hex chars (uuid4, no dashes). */
export const isTradeUid = v => typeof v === "string" && UID_RE.test(v);

/** `v` as a valid uid (dashed / upper-case uuids accepted, like
 *  portfolio._clean_uid), or "" when it is missing or malformed. */
export function cleanTradeUid(v) {
    const s = typeof v === "string" ? v.trim().toLowerCase().replaceAll("-", "") : "";
    return UID_RE.test(s) ? s : "";
}

/** A new client-side trade uid (see docs/api/server-1.1-changes.md). */
export function newTradeUid() {
    const c = globalThis.crypto;
    if (c && typeof c.randomUUID === "function") return c.randomUUID().replaceAll("-", "");
    // randomUUID needs a secure context (https or localhost); fall back to
    // getRandomValues, then Math.random, so plain-http LAN testing still works.
    const bytes = new Uint8Array(16);
    if (c && typeof c.getRandomValues === "function") c.getRandomValues(bytes);
    else for (let i = 0; i < 16; i++) bytes[i] = Math.floor(Math.random() * 256);
    bytes[6] = (bytes[6] & 0x0f) | 0x40;  // uuid4 version and variant bits
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    return Array.from(bytes, b => b.toString(16).padStart(2, "0")).join("");
}

// ── Trade helpers ──────────────────────────────────────────────────────

/** Normalize a raw /trades row (or backup entry) into a uniform shape.
 *  Mirrors trade_from_dict: whole, non-negative share counts, trimmed
 *  upper-case symbol, "" for no tag. Dates stay YYYY-MM-DD strings. A row
 *  without a valid uid (old server, old backup) gets a fresh one. */
export function normalizeTrade(t) {
    return {
        id: t.id,
        uid: cleanTradeUid(t.uid) || newTradeUid(),
        account: (t.account || "").trim(),
        instrument: (t.instrument || "").trim().toUpperCase(),
        share_count: Math.max(0, Math.trunc(Number(t.share_count) || 0)),
        buy_price: Number(t.buy_price) || 0,
        sell_price: t.sell_price === null || t.sell_price === undefined || t.sell_price === ""
            ? null : Number(t.sell_price),
        open_date: t.open_date || null,
        close_date: t.close_date || null,
        notes: t.notes || "",
        is_pending: !!t.is_pending,
        is_short: !!t.is_short,
        tag: (t.tag || "").trim(),
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
    if (!isClosed(t)) return null;
    if (t.is_short) {
        return (Number(t.buy_price) - Number(t.sell_price)) * Number(t.share_count);
    }
    return (Number(t.sell_price) - Number(t.buy_price)) * Number(t.share_count);
}

export function costBasis(t) {
    return Number(t.buy_price) * Number(t.share_count);
}

/** Python-style string order (code points), not localeCompare: sort keys
 *  must order exactly as portfolio.py's sorted() does. */
const cmpStr = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

// ── Holdings (open positions only, grouped by symbol & long/short) ─────

/** compute_holdings_from_trades: shorts first (negative qty), then longs,
 *  each group by symbol. */
export function computeHoldings(trades) {
    const groups = new Map();
    for (const t of trades) {
        if (isClosed(t) || t.is_pending) continue;
        if (!t.instrument || t.share_count <= 0) continue;
        const key = (t.is_short ? `${t.instrument}:SHORT` : t.instrument);
        let g = groups.get(key);
        if (!g) {
            g = {instrument: t.instrument, qty: 0, cost: 0, is_short: t.is_short, notes: []};
            groups.set(key, g);
        }
        g.qty += t.share_count;
        g.cost += t.buy_price * t.share_count;
        if (t.notes) g.notes.push(t.notes);
    }
    const out = [];
    for (const g of groups.values()) {
        if (g.qty <= 0) continue;
        out.push({
            instrument: g.instrument,
            qty: g.is_short ? -g.qty : g.qty,
            avg_cost: g.cost / g.qty,
            notes: g.notes.join(" | "),
        });
    }
    // Python key: (qty >= 0, instrument) — False sorts first, so shorts lead.
    return out.sort((a, b) => (a.qty >= 0) - (b.qty >= 0) || cmpStr(a.instrument, b.instrument));
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

/** compute_portfolio. A null/undefined mark gives market value 0 and no
 *  unrealized P/L. summary.return_pct = unrealized / gross cost. */
export function computePortfolio(holdings, marks, realizedMap = {}) {
    let totalMV = 0;
    let grossMV = 0;
    let grossCost = 0;

    const staged = [];
    for (const h of holdings) {
        const instrument = (h.instrument || "").trim().toUpperCase();
        const qty = Math.trunc(Number(h.qty));
        if (!instrument || !qty) continue;
        const mark = marks[instrument] ?? null;
        const cb = qty * h.avg_cost;
        const mv = mark != null ? mark * qty : 0;
        const upl = mark != null ? mv - cb : 0;
        totalMV += mv;
        grossMV += Math.abs(mv);
        grossCost += Math.abs(cb);
        staged.push({instrument, qty, avg_cost: Number(h.avg_cost), notes: h.notes || "",
            mark, mv, upl, rpl: realizedMap[instrument] || 0});
    }

    let totalUpl = 0;
    const rows = staged.map(s => {
        totalUpl += s.upl;
        return {
            instrument: s.instrument,
            qty: s.qty,
            avg_cost: s.avg_cost,
            mark: s.mark,
            market_value: s.mv,
            weight_pct: grossMV > 0 ? (Math.abs(s.mv) / grossMV) * 100 : 0,
            unrealized_pl: s.upl,
            realized_pl: s.rpl,
            total_pl: s.rpl + s.upl,
            notes: s.notes,
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
        return_pct: grossCost > 0 ? (totalUpl / grossCost) * 100 : null,
    };
    return {rows, summary};
}

// ── Trading days (weekday fallback of portfolio._nyse_day_count) ───────

const DAY_MS = 86_400_000;

/** Midnight local time of a Date (drops any time of day). */
const dayOf = d => new Date(d.getFullYear(), d.getMonth(), d.getDate());

/** Weekdays in [start, end], inclusive, O(1). Same arithmetic as the
 *  fallback in portfolio._nyse_day_count. */
export function tradingDaysBetween(start, end) {
    if (!start || !end) return 0;
    const a = dayOf(start), b = dayOf(end);
    if (b < a) return 0;
    const days = Math.round((b - a) / DAY_MS) + 1;  // round: DST days are 23/25 h
    const full = Math.floor(days / 7), extra = days % 7;
    const first = (a.getDay() + 6) % 7;  // Python weekday(): Monday = 0
    let count = full * 5;
    for (let i = 0; i < extra; i++) if ((first + i) % 7 < 5) count++;
    return count;
}

/** business_days_elapsed_in_year: Jan 1 .. today, inclusive. */
export const businessDaysElapsedInYear = (today = new Date()) =>
    tradingDaysBetween(new Date(today.getFullYear(), 0, 1), today);

/** business_days_remaining_in_year: today .. Dec 31, inclusive (so today
 *  counts in both elapsed and remaining, exactly as in Python). */
export const businessDaysRemainingInYear = (today = new Date()) =>
    tradingDaysBetween(today, new Date(today.getFullYear(), 11, 31));

/** Realized P/L that keeps an even pace to `target` by Dec 31:
 *  target × elapsed / (elapsed + remaining). The same "expected by now"
 *  that compute_goal_progress and the desktop pace rail
 *  (qml_bridge.AccountController._pace_map) use. */
export function goalExpectedByNow(target, today = new Date()) {
    const elapsed = businessDaysElapsedInYear(today);
    const total = elapsed + businessDaysRemainingInYear(today);
    return total > 0 ? Number(target) * elapsed / total : 0;
}

// ── Goal progress ─────────────────────────────────────────────────────

/** compute_goal_progress, same field names as the GoalProgress dataclass.
 *  `unrealized` only feeds unrealized_profit / total_profit; every pace
 *  figure uses realized P/L, as on the desktop. */
export function computeGoalProgress(trades, target, unrealized = 0, today = new Date()) {
    today = dayOf(today);
    let realized = 0;
    for (const t of trades) {
        if (!isClosed(t) || t.is_pending) continue;
        realized += tradeProfit(t) || 0;
    }
    target = Number(target);
    const remainingProfit = target - realized;  // negative once the goal is beaten

    const elapsed = businessDaysElapsedInYear(today);
    const remainingDays = businessDaysRemainingInYear(today);
    const monthsLeft = Math.max(1, 12 - today.getMonth());  // _current_months_remaining
    const calDaysLeft = Math.max(0, Math.round((new Date(today.getFullYear(), 11, 31) - today) / DAY_MS));
    const weeksLeft = Math.max(1, Math.floor((calDaysLeft + 6) / 7));  // _weeks_remaining

    const totalDays = elapsed + remainingDays;
    const expected = totalDays > 0 ? target * elapsed / totalDays : 0;

    return {
        goal_target: target,
        realized_profit: realized,
        unrealized_profit: Number(unrealized) || 0,
        total_profit: realized + (Number(unrealized) || 0),
        remaining_profit: remainingProfit,
        monthly_profit_to_goal: remainingProfit / monthsLeft,
        weekly_profit_to_goal: remainingProfit / weeksLeft,
        daily_profit_to_goal: remainingDays > 0 ? remainingProfit / remainingDays : null,
        avg_daily_profit: elapsed > 0 ? realized / elapsed : null,
        profit_to_match_daily_avg: Math.max(0, expected - realized),
        business_days_elapsed: elapsed,
        business_days_remaining: remainingDays,
    };
}

// ── Date-range filtering ───────────────────────────────────────────────
//
// Mirrors portfolio.filter_trades_by_date_range_with_orig_index (used by
// the desktop's date-range combo): the same window must give the same
// metrics on both clients.
//
// "Date" for filtering = close_date if set, else open_date. Pending
// trades always pass through — hiding them would mask what the user is
// waiting on — and so do undated ones.

/** Parse a YYYY-MM-DD string into a Date in local time, or null. */
function parseISODate(s) {
    if (!s) return null;
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
    if (!m) return null;
    return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
}

const RANGE_KEYS = new Set(["all", "week", "month", "30d", "ytd"]);

/** First day (local midnight) of the window for `key`, or null for "all"
 *  and unknown keys (unknown keys show everything, so a stale saved key
 *  can't strand the UI). */
function rangeStart(key, today) {
    if (!RANGE_KEYS.has(key) || key === "all") return null;
    const t0 = dayOf(today);
    if (key === "week") {  // Monday of this week, like today.weekday()
        return new Date(t0.getFullYear(), t0.getMonth(), t0.getDate() - (t0.getDay() + 6) % 7);
    }
    if (key === "month") return new Date(t0.getFullYear(), t0.getMonth(), 1);
    if (key === "30d") return new Date(t0.getFullYear(), t0.getMonth(), t0.getDate() - 30);
    return new Date(t0.getFullYear(), 0, 1);  // ytd
}

function inWindow(t, start) {
    if (start === null || t.is_pending) return true;
    const ref = parseISODate(t.close_date || t.open_date);
    return !ref || ref >= start;
}

/** True iff `t` falls inside the date range identified by `key`
 *  ("all" | "week" | "month" | "30d" | "ytd"). */
export function tradeInRange(t, key, today = new Date()) {
    return inWindow(t, rangeStart(key, today));
}

/** Filter a trade list by date-range key (original order kept). */
export function filterTradesByDateRange(trades, key, today = new Date()) {
    const start = rangeStart(key, today);
    return start === null ? trades : trades.filter(t => inWindow(t, start));
}

// ── Equity curve ───────────────────────────────────────────────────────
//
// Mirrors AccountController._build_equity_curve in qml_bridge.py: an
// array of {x: epoch ms, y: cumulative realized P/L}, seeded with a $0
// point at 00:00 the day before the first close so the line rises from
// the axis; real points sit at 16:00 local time (NYSE close).

export function buildEquityCurve(trades, mode = "trades") {
    const closed = trades.filter(t => isClosed(t) && !t.is_pending);
    if (closed.length === 0) return [];
    // Stable sort by close_date; ISO strings sort chronologically.
    closed.sort((a, b) => cmpStr(a.close_date, b.close_date));

    const at = (iso, hour) => {
        const d = parseISODate(iso);
        d.setHours(hour, 0, 0, 0);
        return d.getTime();
    };
    const seed = parseISODate(closed[0].close_date);
    seed.setDate(seed.getDate() - 1);
    const pts = [{x: seed.getTime(), y: 0}];

    let running = 0;
    if (mode === "daily") {
        // One end-of-day point per close date (same-day closes summed first).
        const dailyPL = new Map();
        for (const t of closed) {
            dailyPL.set(t.close_date, (dailyPL.get(t.close_date) || 0) + tradeProfit(t));
        }
        for (const [day, pl] of dailyPL) {  // insertion order = date order
            running += pl;
            pts.push({x: at(day, 16), y: running});
        }
    } else {
        for (const t of closed) {
            running += tradeProfit(t);
            pts.push({x: at(t.close_date, 16), y: running});
        }
    }
    return pts;
}

// ── Trade analytics (closed-trade quality stats) ───────────────────────

/** compute_trade_analytics. `today` only drives avg_daily_closed_profit
 *  and est_yearly_profit (Python uses date.today()). */
export function computeAnalytics(trades, today = new Date()) {
    const closed = trades.filter(t => isClosed(t) && !t.is_pending);
    const profits = closed.map(tradeProfit);
    const tradeValues = closed.map(costBasis);
    const sum = arr => arr.reduce((a, b) => a + b, 0);
    const realized = sum(profits);
    const n = closed.length;
    const elapsed = businessDaysElapsedInYear(today);

    const avgProfit = n ? realized / n : null;
    const avgValue = n ? sum(tradeValues) / n : null;
    const totalValue = sum(tradeValues);
    // Avg daily / est. yearly only once something has closed: "$0.00 a
    // day" would read as a forecast when it is really "no data".
    const avgDaily = n && elapsed > 0 ? realized / elapsed : null;

    const wins = profits.filter(p => p > 0);
    const losses = profits.filter(p => p < 0);

    // Drawdown: walk the cumulative-realized curve in close-date order
    // (stable, like Python's sorted). The curve starts at $0.
    let max_drawdown = null;
    let current_drawdown = null;
    if (n) {
        const sorted = closed.slice().sort((a, b) => cmpStr(a.close_date, b.close_date));
        let running = 0, peak = 0, maxDd = 0;
        for (const t of sorted) {
            running += tradeProfit(t);
            if (running > peak) peak = running;
            if (peak - running > maxDd) maxDd = peak - running;
        }
        max_drawdown = maxDd;
        current_drawdown = peak - running;
    }

    return {
        realized_profit: realized,
        closed_trades: n,
        open_trades: trades.filter(t => !isClosed(t)).length,  // pending included, as in Python
        avg_profit_per_trade: avgProfit,
        avg_trade_value: avgValue,
        avg_roi_pct: avgProfit !== null && avgValue ? (avgProfit / avgValue) * 100 : null,
        total_roi_pct: totalValue > 0 ? (realized / totalValue) * 100 : null,
        avg_daily_closed_profit: avgDaily,
        est_yearly_profit: avgDaily === null ? null : avgDaily * 252,  // ~252 NYSE days a year
        win_rate_pct: n ? (wins.length / n) * 100 : null,
        avg_win: wins.length ? sum(wins) / wins.length : null,
        avg_loss: losses.length ? sum(losses) / losses.length : null,
        best_trade: n ? Math.max(...profits) : null,
        worst_trade: n ? Math.min(...profits) : null,
        // Wins and losses both needed; with no losses it is infinite and
        // the UI shows "—" (Python returns None in both edge cases).
        profit_factor: wins.length && losses.length ? sum(wins) / Math.abs(sum(losses)) : null,
        max_drawdown,
        current_drawdown,
    };
}
