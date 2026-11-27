// app.js — Stock Insights PWA: state, data loading, views and dialogs.
//
// No framework and no build step. Each tab is a function that returns a
// fresh DOM subtree for the <main id="view"> outlet; controls that only
// affect one section (date range, tag, curve mode) re-render just that
// section so scroll position and focus survive. All DOM is built with
// ui.js's el()/svg(), which never parse markup, so user data is safe.
//
// Layout and visual language follow docs/design/design-system.md ("Harbor").
// The home view's hero is the pace rail (charts.js).

import {Api} from "./api.js";
import {
    buildEquityCurve,
    computeAnalytics,
    computeGoalProgress,
    computeHoldings,
    computePortfolio,
    filterTradesByDateRange,
    isClosed,
    cleanTradeUid,
    newTradeUid,
    normalizeTrade,
    realizedBySymbol,
    tradeProfit,
    tradeStatus,
} from "./portfolio.js";
import {equityChart, paceRail} from "./charts.js";
import {
    el, fmtClock, fmtIsoDate, icon, ICONS, money, num, pctChange, percent, plural,
    signedMoney, store, tone,
} from "./ui.js";

const DEMO = new URLSearchParams(location.search).has("demo");

// ── Preferences (localStorage, namespaced "si.") ──────────────────────
const PREF_RANGE = "si.dateRange";
const PREF_CURVE = "si.curveMode";
// One-time migration from the un-namespaced keys used before Nov 2026.
for (const [oldKey, newKey] of [["date_range_key", PREF_RANGE], ["equity_curve_mode", PREF_CURVE]]) {
    const v = store.get(oldKey);
    if (v != null) {
        if (store.get(newKey) == null) store.set(newKey, v);
        store.remove(oldKey);
    }
}

// Labels mirror TradesTable.qml's _rangeLabel() on desktop.
const DATE_RANGE_LABELS = {
    all: "All time",
    week: "This week",
    month: "This month",
    "30d": "Last 30 days",
    ytd: "Year to date",
};

const STATUS_LABELS = {
    OPEN: "Open", CLOSED: "Closed", SHORT: "Short", COVERED: "Covered", WAITING: "Pending",
};

const QUOTE_POLL_MS = 60_000;      // live prices while the app is visible
const STALE_RELOAD_MS = 5 * 60_000; // full reload when returning after this long
const TRADE_PAGE = 100;            // trade rows rendered before "Show more"

// ── State ─────────────────────────────────────────────────────────────
const State = {
    accounts: [],            // [{name, goal_target, goal_presets, position}]
    trades: [],              // normalized trades, server order
    byAccount: new Map(),    // account name -> trades (rebuilt on load)
    goalGroup: null,         // {account_names, shared_goal}
    watchlist: [],           // [symbol]
    marks: {},               // {symbol: price}
    quotesOk: true,          // false when the last quote fetch failed
    quotesAt: 0,             // epoch ms of the last successful quote fetch
    loadedAt: 0,             // epoch ms of the last full load
    selectedAccount: "All",
    view: "home",            // home | trades | goals | watchlist | settings
    dateRangeKey: DATE_RANGE_LABELS[store.get(PREF_RANGE)] ? store.get(PREF_RANGE) : "all",
    equityCurveMode: store.get(PREF_CURVE) === "daily" ? "daily" : "trades",
    tagFilter: "",           // not persisted: a stale tag filter hides new trades
    tradeLimit: TRADE_PAGE,
    animated: new Set(),     // goal keys whose pace rail has already animated
};

// ── Data loading ──────────────────────────────────────────────────────
function indexTrades(raw) {
    State.trades = raw.map(normalizeTrade);
    State.byAccount = new Map();
    for (const t of State.trades) {
        if (!State.byAccount.has(t.account)) State.byAccount.set(t.account, []);
        State.byAccount.get(t.account).push(t);
    }
}

async function loadAll() {
    const [accts, rawTrades, gg, wl] = await Promise.all([
        Api.getAccounts(), Api.getTrades(), Api.getGoalGroup(), Api.getWatchlist(),
    ]);
    State.accounts = accts || [];
    indexTrades(rawTrades || []);
    State.goalGroup = gg;
    State.watchlist = wl || [];
    if (State.selectedAccount !== "All"
        && !State.accounts.some(a => a.name === State.selectedAccount)) {
        State.selectedAccount = "All";
    }
    State.loadedAt = Date.now();
    await refreshMarks();
}

/** Re-fetch trades only (after a write); quotes only if new symbols appeared. */
async function reloadTrades() {
    indexTrades(await Api.getTrades() || []);
    const missing = [...openSymbols()].some(s => !(s in State.marks));
    if (missing) await refreshMarks();
}

function openSymbols() {
    const symbols = new Set(State.watchlist);
    for (const t of State.trades) {
        if (!isClosed(t) && !t.is_pending && t.instrument) symbols.add(t.instrument);
    }
    return symbols;
}

/** Fetch live prices. Returns true when any price changed. Never throws:
 *  a failed fetch keeps the last known prices and flags them as stale. */
async function refreshMarks() {
    const symbols = openSymbols();
    if (symbols.size === 0) {
        State.marks = {};
        State.quotesOk = true;
        return false;
    }
    try {
        const next = await Api.getQuotes([...symbols]) || {};
        const changed = JSON.stringify(next) !== JSON.stringify(State.marks);
        State.marks = next;
        State.quotesOk = true;
        State.quotesAt = Date.now();
        return changed;
    } catch (err) {
        console.warn("Quote fetch failed:", err);
        if (err.code === 401) throw err;
        const was = State.quotesOk;
        State.quotesOk = false;
        return was;  // re-render once to show the "prices out of date" note
    }
}

// ── Derived data ──────────────────────────────────────────────────────
function tradesFor(account) {
    return account === "All" ? State.trades : (State.byAccount.get(account) || []);
}

const tradesForSelected = () => tradesFor(State.selectedAccount);

function portfolioOf(trades) {
    return computePortfolio(computeHoldings(trades), State.marks, realizedBySymbol(trades));
}

function applyFilters(trades) {
    let out = filterTradesByDateRange(trades, State.dateRangeKey);
    if (State.tagFilter) out = out.filter(t => t.tag === State.tagFilter);
    return out;
}

/** True once any trade has closed: before that the pace rail shows the
 *  neutral "start" state, as the desktop does. */
const hasClosedTrade = trades => trades.some(t => isClosed(t) && !t.is_pending);

function availableTags() {
    const set = new Set();
    for (const t of State.trades) if (t.tag) set.add(t.tag);
    return [...set].sort((a, b) => a.localeCompare(b));
}

/** The goal that the home pace rail tracks for the current selection, or null.
 *  `covers` is true when the goal counts exactly the selection's trades (only
 *  then is the pace line comparable with the selection's equity curve). */
function goalForSelection() {
    const sel = State.selectedAccount;
    if (sel !== "All") {
        const a = State.accounts.find(x => x.name === sel);
        const target = Number(a?.goal_target) || 0;
        if (target <= 0) return null;
        return {key: `acct:${sel}`, title: `Goal ${money(target, {whole: true})} by Dec 31`,
            target, trades: tradesFor(sel), covers: true};
    }
    const group = State.goalGroup?.account_names || [];
    const shared = Number(State.goalGroup?.shared_goal) || 0;
    if (group.length && shared > 0) {
        const names = new Set(group);
        return {key: "shared", title: `Shared goal ${money(shared, {whole: true})} by Dec 31`,
            target: shared, trades: State.trades.filter(t => names.has(t.account)),
            covers: State.accounts.every(a => names.has(a.name))};
    }
    const combined = State.accounts.reduce((s, a) => s + (Number(a.goal_target) || 0), 0);
    if (combined <= 0) return null;
    return {key: "combined", title: `Combined goal ${money(combined, {whole: true})} by Dec 31`,
        target: combined, trades: State.trades, covers: true};
}

/** TradeIn payload for PUT /trades/{account}[/{uid}]. A 1.1 server stores
 *  `uid` and `tag`; an older one ignores fields it doesn't know. */
function toTradeIn(t) {
    return {
        uid: t.uid,
        instrument: t.instrument, share_count: t.share_count,
        buy_price: t.buy_price, sell_price: t.sell_price,
        open_date: t.open_date, close_date: t.close_date,
        notes: t.notes || "", is_pending: !!t.is_pending, is_short: !!t.is_short,
        tag: (t.tag || "").trim(),
    };
}

// ── Messages ──────────────────────────────────────────────────────────
const OFFLINE_MSG = "Can't reach the sync server. Check your connection and try again.";

/** True for "never reached the server": api.js reports these with code 0
 *  (offline, DNS, timeout); a raw fetch() failure is a TypeError. */
const isOffline = err => err instanceof TypeError || err?.code === 0;

/** Turn a thrown fetch/API error into a sentence for the user. */
function friendly(err, fallback) {
    if (isOffline(err)) return OFFLINE_MSG;
    if (err?.code === 401) return "Your session ended. Sign in again.";
    return err?.message ? `${fallback} ${err.message}` : fallback;
}

let toastTimer = 0;
function toast(msg, kind = "info") {
    const box = document.getElementById("toast");
    if (!box) return;
    clearTimeout(toastTimer);
    box.textContent = msg;
    box.className = `toast is-${kind} is-shown`;
    toastTimer = setTimeout(() => box.classList.remove("is-shown"), kind === "err" ? 5000 : 2600);
}

function handleAuthLoss(err) {
    if (err?.code !== 401) return false;
    stopPolling();
    renderLogin("Your session ended. Sign in again.");
    return true;
}

// ── Boot ──────────────────────────────────────────────────────────────
async function boot() {
    if (DEMO) {
        const {installDemo} = await import("./demo.js");
        installDemo(Api);
    }
    if (!Api.isAuthed()) {
        renderLogin();
        return;
    }
    renderLoading();
    try {
        await loadAll();
        renderShell();
    } catch (err) {
        if (err.code === 401) renderLogin("Your session ended. Sign in again.");
        else renderBootError(err);
    }
}

function renderLoading() {
    document.body.replaceChildren(el("div", {class: "screen-center", role: "status"},
        [el("p", {class: "muted"}, "Loading your portfolio…")]));
}

/** Signed in, but the first load failed: keep the session, offer a retry. */
function renderBootError(err) {
    document.body.replaceChildren(el("main", {class: "screen-center"}, [
        el("section", {class: "panel notice"}, [
            el("h1", {class: "h-section"}, "Can't load your portfolio"),
            el("p", {}, isOffline(err) ? OFFLINE_MSG
                : `The server answered with an error: ${err.message}. Try again in a moment.`),
            el("div", {class: "actions"}, [
                el("button", {class: "btn btn-primary", type: "button", onclick: () => void boot()}, "Try again"),
                el("button", {
                    class: "btn btn-quiet", type: "button",
                    onclick: async () => {
                        await Api.logout();
                        renderLogin();
                    },
                }, "Sign out"),
            ]),
        ]),
    ]));
}

// ── Login ─────────────────────────────────────────────────────────────
function renderLogin(errorMsg = "") {
    stopPolling();
    const host = Api.getServer().replace(/^https?:\/\//, "");
    const user = el("input", {
        id: "usr", class: "input", name: "username", type: "text", required: true,
        autocomplete: "username", autocapitalize: "none", spellcheck: "false",
        value: Api.getUser()?.username || "",
    });
    const pwd = el("input", {id: "pwd", class: "input", name: "password", type: "password", required: true,
        autocomplete: "current-password"});
    const err = el("p", {class: "form-err", role: "alert"}, errorMsg);
    const btn = el("button", {type: "submit", class: "btn btn-primary btn-block"}, "Sign in");

    const form = el("form", {
        class: "login-form",
        onsubmit: async e => {
            e.preventDefault();
            const u = user.value.trim();
            if (!u || !pwd.value) return;
            btn.disabled = true;
            btn.textContent = "Signing in…";
            err.textContent = "";
            try {
                await Api.login(u, pwd.value);
                await loadAll();
                renderShell();
            } catch (ex) {
                err.textContent = isOffline(ex) ? OFFLINE_MSG
                    : ex.code === 401 ? "That username and password don't match. Try again."
                        : `Couldn't sign in. ${ex.message || ""}`.trim();
                btn.disabled = false;
                btn.textContent = "Sign in";
            }
        },
    }, [
        field("Username", user),
        field("Password", pwd),
        err,
        btn,
    ]);

    document.body.replaceChildren(el("main", {class: "login"}, [
        el("div", {class: "login-head"}, [
            el("h1", {class: "login-title"}, "Stock Insights"),
            el("p", {class: "muted"}, "Sign in with the account you use on the desktop app."),
        ]),
        el("section", {class: "panel"}, [form]),
        el("p", {class: "login-foot muted"}, [`Connecting to ${host}. You stay signed in for 30 days.`]),
    ]));
    (user.value ? pwd : user).focus();
}

// ── Shell: top bar, view outlet, tab bar ──────────────────────────────
const TABS = [
    {id: "home", label: "Home", icon: ICONS.home},
    {id: "trades", label: "Trades", icon: ICONS.trades},
    {id: "goals", label: "Goals", icon: ICONS.goals},
    {id: "watchlist", label: "Watchlist", icon: ICONS.watch},
    {id: "settings", label: "Settings", icon: ICONS.settings},
];
const VIEWS = {
    home: () => viewHome(),
    trades: () => viewTrades(),
    goals: () => viewGoals(),
    watchlist: () => viewWatchlist(),
    settings: () => viewSettings(),
};

// Nodes created once per shell; views never query the document for them.
const Shell = {outlet: null, acctSelect: null, refreshBtn: null, tabs: new Map()};

function renderShell() {
    Shell.outlet = el("main", {id: "view", class: "view", tabindex: "-1"});
    Shell.acctSelect = el("select", {
        id: "acct-select", class: "select select-compact",
        onchange: e => {
            State.selectedAccount = e.target.value;
            State.tradeLimit = TRADE_PAGE;
            renderView();
        },
    });
    fillAccountSelect();
    Shell.refreshBtn = el("button", {
        class: "icon-btn", type: "button", "aria-label": "Refresh trades and prices",
        onclick: manualRefresh,
    }, [icon(ICONS.refresh)]);

    const header = el("header", {class: "topbar"}, [
        el("span", {class: "brand"}, "Stock Insights"),
        el("label", {class: "sr-only", for: "acct-select"}, "Account"),
        Shell.acctSelect,
        Shell.refreshBtn,
    ]);

    Shell.tabs.clear();
    const nav = el("nav", {class: "tabbar", "aria-label": "Sections"}, TABS.map(t => {
        const b = el("button", {
            class: "tab", type: "button",
            onclick: () => switchView(t.id),
        }, [icon(t.icon), el("span", {}, t.label)]);
        Shell.tabs.set(t.id, b);
        return b;
    }));

    document.body.replaceChildren(
        el("a", {class: "skip", href: "#view"}, "Skip to content"),
        el("div", {class: "app"}, [header, Shell.outlet, nav]),
        el("div", {id: "toast", class: "toast", role: "status", "aria-live": "polite"}),
    );
    renderView();
    startPolling();
}

function fillAccountSelect() {
    const names = ["All", ...State.accounts.map(a => a.name)];
    Shell.acctSelect.replaceChildren(...names.map(n => {
        const o = el("option", {value: n}, n === "All" ? "All accounts" : n);
        o.selected = n === State.selectedAccount;
        return o;
    }));
}

function switchView(id) {
    if (State.view === id) return;
    State.view = id;
    State.tradeLimit = TRADE_PAGE;
    renderView({fade: true});
    window.scrollTo(0, 0);
}

function renderView({fade = false} = {}) {
    if (!Shell.outlet) return;
    for (const [id, b] of Shell.tabs) {
        if (id === State.view) b.setAttribute("aria-current", "page");
        else b.removeAttribute("aria-current");
    }
    Shell.outlet.classList.toggle("fade-in", fade);
    Shell.outlet.replaceChildren(VIEWS[State.view]());
}

let refreshing = false;
async function manualRefresh() {
    if (refreshing) return;
    refreshing = true;
    Shell.refreshBtn.classList.add("is-busy");
    Shell.refreshBtn.setAttribute("aria-busy", "true");
    try {
        await loadAll();
        fillAccountSelect();
        renderView();
        toast(State.quotesOk ? "Up to date" : "Trades updated. Live prices are unavailable right now.",
            State.quotesOk ? "ok" : "warn");
    } catch (err) {
        if (!handleAuthLoss(err)) toast(friendly(err, "Couldn't refresh."), "err");
    } finally {
        refreshing = false;
        Shell.refreshBtn?.classList.remove("is-busy");
        Shell.refreshBtn?.removeAttribute("aria-busy");
    }
}

// ── Background refresh (only while the page is visible) ───────────────
let pollTimer = 0;

function startPolling() {
    stopPolling();
    if (document.visibilityState === "visible") pollTimer = setInterval(pollQuotes, QUOTE_POLL_MS);
}

function stopPolling() {
    clearInterval(pollTimer);
    pollTimer = 0;
}

/** Don't swap the DOM under someone who is typing, choosing or reading a dialog. */
function safeToRerender() {
    if (document.querySelector("dialog[open]")) return false;
    const a = document.activeElement;
    return !(a && Shell.outlet?.contains(a) && a.matches("input, select, textarea"));
}

async function pollQuotes() {
    if (!Shell.outlet?.isConnected || State.view === "settings") return;
    try {
        if (await refreshMarks() && safeToRerender()) renderView();
    } catch (err) {
        handleAuthLoss(err);
    }
}

document.addEventListener("visibilitychange", async () => {
    if (document.visibilityState !== "visible") {
        stopPolling();
        return;
    }
    if (!Shell.outlet?.isConnected) return;
    const now = Date.now();
    try {
        if (now - State.loadedAt > STALE_RELOAD_MS) {
            await loadAll();
            fillAccountSelect();
            if (safeToRerender()) renderView();
        } else if (now - State.quotesAt > QUOTE_POLL_MS) {
            await pollQuotes();
        }
    } catch (err) {
        // Offline on resume: keep showing what we have.
        if (!handleAuthLoss(err)) console.warn("Resume refresh failed:", err);
    }
    startPolling();
});

// ── Shared bits ───────────────────────────────────────────────────────
function field(label, input, hint = null) {
    return el("label", {class: "field"}, [
        el("span", {class: "field-label"}, label),
        input,
        hint ? el("span", {class: "field-hint"}, hint) : null,
    ]);
}

function kv(rows) {
    return el("dl", {class: "kv"}, rows.filter(Boolean).map(([k, v, cls = ""]) =>
        el("div", {class: "kv-row"}, [el("dt", {}, k), el("dd", {class: "num " + cls}, v)])));
}

function panel(title, children, {meta = null, cls = ""} = {}) {
    return el("section", {class: "panel " + cls}, [
        title ? el("div", {class: "panel-head"}, [
            el("h2", {class: "h-panel"}, title),
            meta ? el("span", {class: "panel-meta"}, meta) : null,
        ]) : null,
        ...[].concat(children),
    ]);
}

function empty(text, action = null) {
    return el("div", {class: "empty"}, [el("p", {}, text), action]);
}

function statusPill(t) {
    const s = tradeStatus(t);
    return el("span", {class: "pill pill-" + s.toLowerCase()}, STATUS_LABELS[s] || s);
}

function selectControl(label, value, options, onChange) {
    const id = `sel-${label.toLowerCase().replace(/\W+/g, "-")}`;
    const sel = el("select", {id, class: "select", onchange: e => onChange(e.target.value)},
        options.map(([v, text]) => {
            const o = el("option", {value: v}, text);
            o.selected = v === value;
            return o;
        }));
    return el("div", {class: "control"}, [el("label", {for: id, class: "control-label"}, label), sel]);
}

function filterControls(onChange) {
    const tags = availableTags();
    return el("div", {class: "filters"}, [
        selectControl("Range", State.dateRangeKey, Object.entries(DATE_RANGE_LABELS), v => {
            State.dateRangeKey = DATE_RANGE_LABELS[v] ? v : "all";
            store.set(PREF_RANGE, State.dateRangeKey);
            onChange("sel-range");
        }),
        tags.length ? selectControl("Tag", State.tagFilter,
            [["", "All tags"], ...tags.map(t => [t, t])], v => {
                State.tagFilter = v;
                onChange("sel-tag");
            }) : null,
    ]);
}

/** Replace `node` with `build()` and put focus back on the control the
 *  user just changed (it was destroyed with the old subtree). */
function rerenderSection(node, build, focusId) {
    const next = build();
    node.replaceWith(next);
    if (focusId) document.getElementById(focusId)?.focus();
    return next;
}

// ── View: Home ────────────────────────────────────────────────────────
function viewHome() {
    const trades = tradesForSelected();
    const {rows, summary} = portfolioOf(trades);
    const goal = goalForSelection();

    let hero;
    if (goal) {
        const realized = computeGoalProgress(goal.trades, goal.target).realized_profit;
        const animate = !State.animated.has(goal.key);
        State.animated.add(goal.key);
        hero = el("div", {class: "panel panel-hero"}, [
            paceRail({title: goal.title, target: goal.target, realized,
                hasClosed: hasClosedTrade(goal.trades), animate}),
        ]);
    } else {
        hero = el("div", {class: "panel panel-hero"}, [
            el("h2", {class: "pace-goal"}, State.selectedAccount === "All"
                ? "Total profit and loss" : `${State.selectedAccount} profit and loss`),
            el("p", {class: "pace-value num"}, signedMoney(summary.total_pl)),
            el("p", {class: "muted"}, "No goal set for this account. Set a yearly goal in the desktop app to see your pace here."),
        ]);
    }

    const priceNote = el("p", {class: "price-note" + (State.quotesOk ? " muted" : " is-warn"), role: "status"},
        State.quotesOk
            ? (State.quotesAt ? `Prices updated ${fmtClock(State.quotesAt)}` : "")
            : "Live prices are unavailable. Showing the last known prices.");

    const stats = el("section", {class: "stats", "aria-label": "Summary"}, [
        stat("Total P/L", signedMoney(summary.total_pl), tone(summary.total_pl), pctChange(summary.return_pct)),
        stat("Unrealised", signedMoney(summary.unrealized_pl), tone(summary.unrealized_pl)),
        stat("Market value", money(summary.market_value)),
        stat("Open positions", String(summary.positions)),
    ]);

    // Holdings are a "right now" snapshot, so the date filter never applies
    // (same as desktop's HoldingsTable).
    const holdings = panel("Open positions", rows.length
        ? holdingsList(rows)
        : empty("No open positions. Log a trade to start tracking.",
            el("button", {class: "btn btn-secondary", type: "button", onclick: () => openTradeEditor(null)}, "Log trade")),
    {meta: rows.length ? plural(rows.length, "symbol") : null});

    let perf;
    const buildPerf = () => performanceSection(trades, goal, focusId => {
        perf = rerenderSection(perf, buildPerf, focusId);
    });
    perf = buildPerf();

    return el("div", {class: "stack"}, [hero, priceNote, stats, holdings, perf]);
}

function stat(label, value, cls = "", sub = null) {
    return el("div", {class: "stat"}, [
        el("span", {class: "stat-label"}, label),
        el("span", {class: "stat-value num " + cls}, value),
        sub ? el("span", {class: "stat-sub num " + cls}, sub) : null,
    ]);
}

function holdingsList(rows) {
    return el("ul", {class: "rows"}, rows.map(r => {
        const cost = Math.abs(r.qty * r.avg_cost);
        const uplPct = r.mark != null && cost > 0 ? (r.unrealized_pl / cost) * 100 : null;
        return el("li", {}, [el("button", {
            class: "row", type: "button", onclick: () => showHoldingDetail(r),
            "aria-label": `${r.instrument}, ${Math.abs(r.qty)} shares${r.qty < 0 ? " short" : ""}, `
                + `total P/L ${signedMoney(r.total_pl)}. Show details`,
        }, [
            el("span", {class: "row-main"}, [
                el("span", {class: "row-title"}, [
                    el("span", {class: "sym"}, r.instrument),
                    r.qty < 0 ? el("span", {class: "pill pill-short"}, "Short") : null,
                ]),
                el("span", {class: "row-sub num"},
                    `${num(Math.abs(r.qty))} shares, avg ${money(r.avg_cost)}, last ${r.mark == null ? "unavailable" : money(r.mark)}`),
            ]),
            el("span", {class: "row-end"}, [
                el("span", {class: "num row-value " + tone(r.total_pl)}, signedMoney(r.total_pl)),
                el("span", {class: "num row-sub " + tone(uplPct)}, pctChange(uplPct)),
            ]),
        ])]);
    }));
}

/** Equity curve + analytics for the filtered trades. `onChange(focusId)`
 *  re-renders just this section. */
function performanceSection(trades, goal, onChange) {
    const ranged = applyFilters(trades);
    const curve = buildEquityCurve(ranged, State.equityCurveMode);
    const an = computeAnalytics(ranged);
    // The pace line only compares with an all-time curve of the goal's trades.
    const paceTarget = goal && goal.covers && State.dateRangeKey === "all" && !State.tagFilter
        ? goal.target : null;

    const modeBtn = (mode, label) => el("button", {
        type: "button", class: "seg-btn", id: `curve-${mode}`,
        "aria-pressed": String(State.equityCurveMode === mode),
        onclick: () => {
            if (State.equityCurveMode === mode) return;
            State.equityCurveMode = mode;
            store.set(PREF_CURVE, mode);
            onChange(`curve-${mode}`);
        },
    }, label);
    const closedCount = Math.max(0, curve.length - 1);

    return el("section", {class: "stack-tight", "aria-labelledby": "perf-h"}, [
        el("div", {class: "section-head"}, [el("h2", {class: "h-section", id: "perf-h"}, "Performance")]),
        filterControls(onChange),
        panel("Realised P/L over time", curve.length ? [
            closedCount >= 3 ? el("div", {class: "seg", role: "group", "aria-label": "Curve detail"},
                [modeBtn("trades", "Per trade"), modeBtn("daily", "Daily")]) : null,
            equityChart(curve, {paceTarget}),
        ] : empty(State.dateRangeKey === "all" && !State.tagFilter
            ? "No closed trades yet. Close a trade to see your curve."
            : "No closed trades in this range. Try a wider range."),
        {meta: curve.length ? signedMoney(curve[curve.length - 1].y) : null}),
        panel("Trade analytics", kv([
            ["Closed trades", String(an.closed_trades)],
            ["Open trades", String(an.open_trades)],
            ["Win rate", percent(an.win_rate_pct)],
            ["Average win", signedMoney(an.avg_win), tone(an.avg_win)],
            ["Average loss", signedMoney(an.avg_loss), tone(an.avg_loss)],
            ["Best trade", signedMoney(an.best_trade), tone(an.best_trade)],
            ["Worst trade", signedMoney(an.worst_trade), tone(an.worst_trade)],
            // null with no losses (infinite) or no wins, as on the desktop.
            ["Profit factor", an.profit_factor == null ? "—" : an.profit_factor.toFixed(2)],
            ["Largest drawdown", an.max_drawdown ? money(-an.max_drawdown) : "—", an.max_drawdown ? "bad" : ""],
            ["Current drawdown", an.current_drawdown ? money(-an.current_drawdown) : "—", an.current_drawdown ? "bad" : ""],
        ]), {meta: DATE_RANGE_LABELS[State.dateRangeKey] + (State.tagFilter ? `, tag ${State.tagFilter}` : "")}),
    ]);
}

// ── Holding drill-down (mirrors desktop SymbolHistoryDialog) ──────────
function showHoldingDetail(r) {
    const sym = r.instrument;
    const symTrades = tradesForSelected().filter(t => t.instrument === sym);
    const curve = buildEquityCurve(symTrades, "trades");

    openDialog(sym, [
        kv([
            ["Quantity", `${num(Math.abs(r.qty))}${r.qty < 0 ? " (short)" : ""}`],
            ["Average cost", money(r.avg_cost)],
            ["Last price", r.mark == null ? "Unavailable" : money(r.mark)],
            ["Market value", money(r.market_value)],
            ["Portfolio weight", percent(r.weight_pct)],
            ["Unrealised P/L", signedMoney(r.unrealized_pl), tone(r.unrealized_pl)],
            ["Realised P/L", signedMoney(r.realized_pl), tone(r.realized_pl)],
            ["Total P/L", signedMoney(r.total_pl), tone(r.total_pl)],
        ]),
        r.notes ? el("div", {class: "notes"}, [el("h3", {class: "h-sub"}, "Notes"), el("p", {}, r.notes)]) : null,
        curve.length ? el("div", {}, [el("h3", {class: "h-sub"}, "Realised P/L"), equityChart(curve)]) : null,
        el("h3", {class: "h-sub"}, `All trades (${symTrades.length})`),
        symbolTradeList(symTrades),
    ]);
}

/** Chronological, read-only list (entry to exit reads top to bottom). */
function symbolTradeList(trades) {
    const sorted = trades.slice().sort((a, b) => {
        const ad = a.close_date || a.open_date || "", bd = b.close_date || b.open_date || "";
        return ad < bd ? -1 : ad > bd ? 1 : 0;
    });
    return el("ul", {class: "rows rows-static"}, sorted.map(t => {
        const p = tradeProfit(t);
        return el("li", {class: "row"}, [
            el("span", {class: "row-main"}, [
                el("span", {class: "row-title"}, [
                    el("span", {}, fmtIsoDate(t.close_date || t.open_date)), statusPill(t),
                    t.tag ? el("span", {class: "pill"}, t.tag) : null,
                ]),
                el("span", {class: "row-sub num"}, `${num(t.share_count)} shares at ${money(t.buy_price)}`),
            ]),
            (p == null
                ? el("span", {class: "num row-value muted", "aria-label": "No realised P/L yet"}, "—")
                : el("span", {class: "num row-value " + tone(p)}, signedMoney(p))),
        ]);
    }));
}

// ── View: Trades ──────────────────────────────────────────────────────
function viewTrades() {
    const all = tradesForSelected();
    let listNode;

    const buildList = () => {
        const ranged = applyFilters(all);
        const newest = ranged.slice().reverse();  // server order is oldest first
        const shown = newest.slice(0, State.tradeLimit);
        const caption = `${ranged.length} of ${plural(all.length, "trade")}`;

        let body;
        if (all.length === 0) {
            body = empty("No trades yet. Log your first trade to start tracking.");
        } else if (newest.length === 0) {
            body = empty("No trades match these filters. Try a wider range or another tag.");
        } else {
            body = [
                el("ul", {class: "rows"}, shown.map(t => el("li", {}, [tradeRow(t)]))),
                newest.length > shown.length ? el("button", {
                    class: "btn btn-secondary btn-block", type: "button", id: "more-trades",
                    onclick: () => {
                        State.tradeLimit += TRADE_PAGE;
                        listNode = rerenderSection(listNode, buildList, "more-trades");
                    },
                }, `Show ${Math.min(TRADE_PAGE, newest.length - shown.length)} more`) : null,
            ];
        }
        return el("div", {class: "stack-tight"}, [
            filterControls(focusId => {
                State.tradeLimit = TRADE_PAGE;
                listNode = rerenderSection(listNode, buildList, focusId);
            }),
            el("p", {class: "muted small", role: "status"}, caption),
            panel(null, body, {cls: "panel-flush"}),
        ]);
    };
    listNode = buildList();

    return el("div", {class: "stack"}, [
        el("div", {class: "section-head"}, [
            el("h1", {class: "h-section"}, "Trades"),
            el("button", {class: "btn btn-primary", type: "button", onclick: () => openTradeEditor(null)}, "Log trade"),
        ]),
        listNode,
    ]);
}

function tradeRow(t) {
    const p = tradeProfit(t);
    return el("button", {class: "row", type: "button", onclick: () => openTradeEditor(t)}, [
        el("span", {class: "row-main"}, [
            el("span", {class: "row-title"}, [
                el("span", {class: "sym"}, t.instrument || "—"), statusPill(t),
                t.tag ? el("span", {class: "pill"}, t.tag) : null,
            ]),
            el("span", {class: "row-sub num"},
                `${num(t.share_count)} shares at ${money(t.buy_price)}`
                + (State.selectedAccount === "All" && t.account ? `, ${t.account}` : "")),
        ]),
        el("span", {class: "row-end"}, [
            (p == null
                ? el("span", {class: "num row-value muted", "aria-label": "No realised P/L yet"}, "—")
                : el("span", {class: "num row-value " + tone(p)}, signedMoney(p))),
            el("span", {class: "row-sub"}, fmtIsoDate(t.close_date || t.open_date || "")),
        ]),
    ]);
}

// ── Trade editor ──────────────────────────────────────────────────────
function openTradeEditor(existing) {
    const names = State.accounts.map(a => a.name);
    if (names.length === 0) {
        toast("Create an account in the desktop app first, then log trades here.", "warn");
        return;
    }
    const t = existing ? {...existing} : {
        account: State.selectedAccount === "All" ? names[0] : State.selectedAccount,
        instrument: "", share_count: "", buy_price: "", sell_price: null,
        open_date: new Date().toLocaleDateString("en-CA"),  // YYYY-MM-DD, local
        close_date: null, notes: "", tag: "", is_pending: false, is_short: false,
    };

    const input = attrs => el("input", {class: "input", ...attrs});
    const check = (name, label, on) => {
        const box = el("input", {type: "checkbox", name});
        box.checked = !!on;
        return el("label", {class: "check"}, [box, el("span", {}, label)]);
    };
    const notes = el("textarea", {class: "input", name: "notes", rows: "3"});
    notes.value = t.notes || "";
    const acct = el("select", {class: "select", name: "account", required: true},
        names.map(n => {
            const o = el("option", {value: n}, n);
            o.selected = n === t.account;
            return o;
        }));
    const err = el("p", {class: "form-err", role: "alert"});
    const submit = el("button", {type: "submit", class: "btn btn-primary"}, existing ? "Save changes" : "Log trade");

    const form = el("form", {class: "form", novalidate: false}, [
        field("Account", acct),
        field("Symbol", input({name: "instrument", required: true, autocapitalize: "characters",
            autocomplete: "off", spellcheck: "false", value: t.instrument, placeholder: "AAPL"})),
        el("div", {class: "grid-2"}, [
            field("Shares", input({name: "share_count", type: "number", inputmode: "numeric",
                min: "1", step: "1", required: true, value: t.share_count})),
            field("Entry price", input({name: "buy_price", type: "number", inputmode: "decimal",
                step: "0.01", min: "0", required: true, value: t.buy_price})),
        ]),
        el("div", {class: "grid-2"}, [
            field("Open date", input({name: "open_date", type: "date", value: t.open_date || ""})),
            field("Close date", input({name: "close_date", type: "date", value: t.close_date || ""})),
        ]),
        field("Exit price", input({name: "sell_price", type: "number", inputmode: "decimal",
            step: "0.01", min: "0", value: t.sell_price ?? ""}), "Leave blank while the position is open. A trade is closed once it has an exit price and a close date."),
        el("fieldset", {class: "checks"}, [
            el("legend", {class: "sr-only"}, "Trade type"),
            check("is_short", "Short position", t.is_short),
            check("is_pending", "Pending order (not filled yet)", t.is_pending),
        ]),
        field("Tag", input({name: "tag", value: t.tag || "", placeholder: "For example swing or earnings",
            list: "tag-options", maxlength: "40", autocomplete: "off"})),
        el("datalist", {id: "tag-options"}, availableTags().map(v => el("option", {value: v}))),
        field("Notes", notes),
        err,
        el("div", {class: "actions actions-split"}, [
            existing ? el("button", {type: "button", class: "btn btn-danger",
                onclick: () => deleteTrade(existing)}, "Delete trade") : el("span"),
            submit,
        ]),
    ]);
    form.addEventListener("submit", async e => {
        e.preventDefault();
        await saveTradeFromForm(existing, form, submit, err);
    });

    openDialog(existing ? `Edit ${existing.instrument} trade` : "Log trade", form);
}

// ── Trade writes ──────────────────────────────────────────────────────
// A 1.1 server takes one trade at a time (PUT/DELETE /trades/{account}/{uid});
// moving a trade is a PUT under the new account. A pre-1.1 server answers
// 404/405 (or 503 while its database is unmigrated) on those routes,
// after which this session uses the old
// whole-account replace (PUT /trades/{account}) for every write.
let perTradeRoutes = true;

/** Runs `perTrade()`; on a pre-1.1 server runs `legacy()` instead. */
async function writeTrades(perTrade, legacy) {
    if (perTradeRoutes) {
        try {
            return await perTrade();
        } catch (ex) {
            if (!Api.isLegacyRouteError(ex)) throw ex;
            perTradeRoutes = false;
            console.info("Server has no per-trade routes; using whole-account saves.");
        }
    }
    return legacy();
}

/** Upsert one trade (new or edited, possibly moved to another account). */
function saveTrade(existing, target, trade) {
    return writeTrades(
        async () => {
            try {
                return await Api.putTrade(target, toTradeIn(trade));
            } catch (ex) {
                // 409: the uid belongs to someone else's trade. Take a fresh
                // uid and try once more; never loop.
                if (ex?.code !== 409) throw ex;
                trade.uid = newTradeUid();
                return Api.putTrade(target, toTradeIn(trade));
            }
        },
        async () => {
            const touched = new Set([target]);
            if (existing?.account && existing.account !== target) touched.add(existing.account);
            for (const name of touched) {
                const list = tradesFor(name).filter(x => x.uid !== trade.uid);
                if (name === target) list.push(trade);
                await Api.replaceAccountTrades(name, list.map(toTradeIn));
            }
        });
}

function removeTrade(existing) {
    return writeTrades(
        () => Api.deleteTradeByUid(existing.account, existing.uid),
        () => Api.replaceAccountTrades(existing.account,
            tradesFor(existing.account).filter(x => x.uid !== existing.uid).map(toTradeIn)));
}

async function saveTradeFromForm(existing, form, submit, err) {
    const fd = new FormData(form);
    const incoming = {
        instrument: String(fd.get("instrument")).trim().toUpperCase(),
        share_count: Number(fd.get("share_count")),
        buy_price: Number(fd.get("buy_price")),
        sell_price: fd.get("sell_price") === "" ? null : Number(fd.get("sell_price")),
        open_date: fd.get("open_date") || null,
        close_date: fd.get("close_date") || null,
        notes: String(fd.get("notes") || ""),
        tag: String(fd.get("tag") || "").trim().slice(0, 40),  // desktop caps at 40
        is_pending: fd.get("is_pending") === "on",
        is_short: fd.get("is_short") === "on",
    };
    const target = String(fd.get("account"));
    if (!incoming.instrument) return void (err.textContent = "Enter a symbol, for example AAPL.");
    if (!(incoming.share_count >= 1) || !Number.isInteger(incoming.share_count)) {
        return void (err.textContent = "Shares must be a whole number of 1 or more.");
    }
    err.textContent = "";
    const label = submit.textContent;
    submit.disabled = true;
    submit.textContent = "Saving…";

    try {
        // A new trade gets its uid here, so a retried save can't duplicate it.
        await saveTrade(existing, target, {...incoming, account: target, uid: existing?.uid || newTradeUid()});
        closeDialog();
        await reloadTrades();
        renderView();
        toast(existing ? "Trade saved" : "Trade logged", "ok");
    } catch (ex) {
        if (handleAuthLoss(ex)) return;
        err.textContent = isOffline(ex)
            ? "Can't reach the sync server, so the trade wasn't saved. Try again when you're back online."
            : friendly(ex, "Couldn't save the trade.");
        submit.disabled = false;
        submit.textContent = label;
    }
}

async function deleteTrade(existing) {
    if (!confirm(`Delete this ${existing.instrument} trade? This can't be undone.`)) return;
    try {
        await removeTrade(existing);
        closeDialog();
        await reloadTrades();
        renderView();
        toast("Trade deleted", "ok");
    } catch (ex) {
        if (!handleAuthLoss(ex)) toast(friendly(ex, "Couldn't delete the trade."), "err");
    }
}

// ── View: Goals ───────────────────────────────────────────────────────
function viewGoals() {
    const cards = [];
    const group = State.goalGroup?.account_names || [];
    const shared = Number(State.goalGroup?.shared_goal) || 0;
    if (group.length && shared > 0) {
        const names = new Set(group);
        cards.push(goalPanel(`Shared goal: ${group.join(", ")}`, shared,
            State.trades.filter(t => names.has(t.account))));
    }
    for (const a of State.accounts) {
        const target = Number(a.goal_target) || 0;
        if (target > 0) cards.push(goalPanel(a.name, target, tradesFor(a.name)));
    }
    return el("div", {class: "stack"}, [
        el("div", {class: "section-head"}, [el("h1", {class: "h-section"}, "Goals")]),
        ...(cards.length ? cards : [panel(null,
            empty("No goals yet. Set a yearly goal for an account in the desktop app and it shows up here."))]),
    ]);
}

function goalPanel(name, target, trades) {
    const prog = computeGoalProgress(trades, target);
    const {summary} = portfolioOf(trades);
    return panel(name, [
        paceRail({title: `${money(target, {whole: true})} by Dec 31`, target, realized: prog.realized_profit,
            hasClosed: hasClosedTrade(trades), compact: true}),
        kv([
            ["Total P/L incl. open positions", signedMoney(summary.total_pl), tone(summary.total_pl)],
            ["Left to reach the goal", money(prog.remaining_profit)],
            ["Needed per month", money(prog.monthly_profit_to_goal)],
            ["Needed per week", money(prog.weekly_profit_to_goal)],
            ["Needed per trading day", money(prog.daily_profit_to_goal)],
            ["Average per trading day so far", signedMoney(prog.avg_daily_profit), tone(prog.avg_daily_profit)],
            ["Trading days left", String(prog.business_days_remaining)],
        ]),
    ]);
}

// ── View: Watchlist ───────────────────────────────────────────────────
function viewWatchlist() {
    const inp = el("input", {
        id: "watch-add", class: "input", name: "symbol", required: true, placeholder: "Symbol, for example MSFT",
        autocapitalize: "characters", autocomplete: "off", spellcheck: "false", maxlength: "12",
    });
    const form = el("form", {class: "inline-form", onsubmit: e => {
        e.preventDefault();
        void addWatchSymbol(inp.value);
    }}, [
        el("label", {for: "watch-add", class: "sr-only"}, "Symbol to watch"),
        inp,
        el("button", {class: "btn btn-primary", type: "submit"}, "Add"),
    ]);

    const list = State.watchlist.length ? el("ul", {class: "rows rows-static"}, State.watchlist.map(sym => {
        const price = State.marks[sym];
        return el("li", {class: "row"}, [
            el("span", {class: "sym row-main"}, sym),
            el("span", {class: "num row-value"}, price == null ? "No price" : money(price)),
            el("button", {
                class: "icon-btn", type: "button", "aria-label": `Remove ${sym} from watchlist`,
                onclick: () => removeWatchSymbol(sym),
            }, [icon(ICONS.close)]),
        ]);
    })) : empty("Your watchlist is empty. Add a symbol to follow its live price.");

    return el("div", {class: "stack"}, [
        el("div", {class: "section-head"}, [el("h1", {class: "h-section"}, "Watchlist")]),
        panel(null, [form]),
        panel(null, list, {cls: "panel-flush"}),
    ]);
}

async function addWatchSymbol(raw) {
    const sym = (raw || "").trim().toUpperCase();
    if (!sym) return;
    if (State.watchlist.includes(sym)) {
        toast(`${sym} is already on your watchlist`, "info");
        return;
    }
    const next = [...State.watchlist, sym];
    try {
        await Api.setWatchlist(next);
        State.watchlist = next;
        await refreshMarks();
        renderView();
        document.getElementById("watch-add")?.focus();
        toast(`${sym} added`, "ok");
    } catch (ex) {
        if (!handleAuthLoss(ex)) toast(friendly(ex, `Couldn't add ${sym}.`), "err");
    }
}

async function removeWatchSymbol(sym) {
    const next = State.watchlist.filter(s => s !== sym);
    try {
        await Api.setWatchlist(next);
        State.watchlist = next;
        renderView();
        toast(`${sym} removed`, "ok");
    } catch (ex) {
        if (!handleAuthLoss(ex)) toast(friendly(ex, `Couldn't remove ${sym}.`), "err");
    }
}

// ── View: Settings (account, backup, sign out) ────────────────────────
function viewSettings() {
    const user = Api.getUser();
    const host = Api.getServer().replace(/^https?:\/\//, "");
    return el("div", {class: "stack"}, [
        el("div", {class: "section-head"}, [el("h1", {class: "h-section"}, "Settings")]),
        panel("Account", [
            kv([["Signed in as", user?.username || "—"], ["Server", host]]),
            el("div", {class: "actions"}, [el("button", {
                class: "btn btn-secondary", type: "button",
                onclick: async () => {
                    await Api.logout();
                    renderLogin();
                },
            }, "Sign out")]),
        ]),
        panel("Backup", [
            el("p", {class: "muted"}, "Backups use the same file format as the desktop app, so you can restore them on either."),
            el("div", {class: "actions"}, [
                el("button", {class: "btn btn-primary", type: "button", onclick: downloadBackup}, "Back up data"),
                el("button", {class: "btn btn-secondary", type: "button", onclick: pickBackupFile}, "Restore from backup"),
            ]),
            el("p", {class: "muted small"}, "Goal targets in a backup are restored by the desktop app only."),
        ]),
    ]);
}

// ── Backup / restore (format = stock_insights/io_utils.py, schema 1) ──
const BACKUP_SCHEMA_VERSION = 1;

function buildBackupSnapshot() {
    return {
        schema_version: BACKUP_SCHEMA_VERSION,
        exported_at: new Date().toISOString(),
        username: Api.getUser()?.username || "",
        accounts: State.accounts.map(a => a.name),
        // Shipped for desktop restores; the PWA has no endpoint to write them.
        goal_targets: Object.fromEntries(State.accounts.map(a => [a.name, Number(a.goal_target) || 0])),
        goal_presets: Object.fromEntries(State.accounts.map(a => [a.name, (a.goal_presets || []).map(Number)])),
        goal_group: {
            shared_accounts: State.goalGroup?.account_names || [],
            shared_goal: Number(State.goalGroup?.shared_goal) || 0,
        },
        watchlist: [...State.watchlist],
        trades: State.trades.map(t => ({...toTradeIn(t), account: t.account || ""})),
    };
}

function downloadBackup() {
    const blob = new Blob([JSON.stringify(buildBackupSnapshot(), null, 2)], {type: "application/json"});
    const url = URL.createObjectURL(blob);
    const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    const a = el("a", {href: url, download: `stock_insights_backup_${stamp}.json`});
    document.body.appendChild(a);
    a.click();
    a.remove();
    // Some mobile browsers start the download asynchronously.
    setTimeout(() => URL.revokeObjectURL(url), 10_000);
    toast("Backup downloaded", "ok");
}

function pickBackupFile() {
    const input = el("input", {type: "file", accept: "application/json,.json", hidden: true});
    input.addEventListener("change", async () => {
        const f = input.files?.[0];
        input.remove();
        if (!f) return;
        let snap;
        try {
            snap = JSON.parse(await f.text());
        } catch {
            toast("That file isn't a Stock Insights backup (it isn't valid JSON).", "err");
            return;
        }
        const errors = validateBackupShape(snap);
        if (errors.length) {
            alert("This backup can't be restored:\n\n- " + errors.slice(0, 8).join("\n- "));
            return;
        }
        const ok = confirm("Restoring replaces your current data on the server with this backup:\n\n"
            + `${plural(snap.accounts.length, "account")}, ${plural(snap.trades.length, "trade")}, `
            + `${plural(snap.watchlist.length, "watchlist symbol")}\n`
            + `Backed up ${snap.exported_at || "at an unknown time"}\n\nRestore now?`);
        if (!ok) return;
        try {
            const failed = await applyBackupSnapshot(snap);
            await loadAll();
            fillAccountSelect();
            renderView();
            toast(failed.length ? `Restored, except: ${failed.join(", ")}. Try those again.` : "Backup restored",
                failed.length ? "warn" : "ok");
        } catch (ex) {
            if (!handleAuthLoss(ex)) toast(friendly(ex, "Restore failed."), "err");
        }
    });
    document.body.appendChild(input);
    input.click();
}

// Mirrors stock_insights/io_utils.py::validate_backup — refuse anything
// doubtful rather than half-restore it.
function validateBackupShape(snap) {
    if (!snap || typeof snap !== "object" || Array.isArray(snap)) return ["The file is not a JSON object."];
    const errs = [];
    const numeric = v => typeof v === "number" && !Number.isNaN(v);
    for (const [k, kind] of [["schema_version", "number"], ["accounts", "array"], ["watchlist", "array"], ["trades", "array"]]) {
        if (!(k in snap)) errs.push(`Missing "${k}".`);
        else if (kind === "number" && !numeric(snap[k])) errs.push(`"${k}" should be a number.`);
        else if (kind === "array" && !Array.isArray(snap[k])) errs.push(`"${k}" should be a list.`);
    }
    if (errs.length) return errs;
    if (snap.schema_version !== BACKUP_SCHEMA_VERSION) {
        errs.push(`Backup format ${snap.schema_version} isn't supported (expected ${BACKUP_SCHEMA_VERSION}).`);
    }
    snap.trades.forEach((t, i) => {
        if (!t || typeof t !== "object") return void errs.push(`Trade ${i + 1} is not an object.`);
        if (typeof t.instrument !== "string" || !t.instrument.trim()) errs.push(`Trade ${i + 1} has no symbol.`);
        if (!numeric(t.share_count)) errs.push(`Trade ${i + 1} has no share count.`);
        if (!numeric(t.buy_price)) errs.push(`Trade ${i + 1} has no entry price.`);
    });
    return errs;
}

/** Applies a validated snapshot. Returns the names of the parts that failed. */
async function applyBackupSnapshot(snap) {
    const failed = [];
    const attempt = async (name, fn) => {
        try {
            await fn();
        } catch (ex) {
            if (ex?.code === 401) throw ex;
            console.warn(`Restore: ${name} failed`, ex);
            failed.push(name);
        }
    };
    if (snap.accounts.length) await attempt("accounts", () => Api.saveAccounts(snap.accounts));
    await attempt("watchlist", () => Api.setWatchlist(snap.watchlist));

    const byAccount = new Map();
    const seenUids = new Set();
    for (const t of snap.trades) {
        const acct = (t.account || "").trim() || snap.accounts[0] || "Default";
        if (!byAccount.has(acct)) byAccount.set(acct, []);
        // Keep a valid, first-seen uid (the server keeps it). Drop a malformed
        // or repeated one and let the server generate it, rather than have
        // the account rejected (422) or one trade overwrite another.
        const {uid, ...rest} = t;
        const clean = cleanTradeUid(uid);
        const keep = clean && !seenUids.has(clean);
        if (keep) seenUids.add(clean);
        byAccount.get(acct).push(keep ? {...rest, uid: clean} : rest);
    }
    for (const [acct, ts] of byAccount) {
        await attempt(`trades for ${acct}`, () => Api.replaceAccountTrades(acct, ts));
    }
    const gg = snap.goal_group;
    if (gg && Array.isArray(gg.shared_accounts)) {
        await attempt("shared goal", () => Api.setGoalGroup(gg.shared_accounts, Number(gg.shared_goal) || 0));
    }
    return failed;
}

// ── Dialog (native <dialog>: focus trap, Escape and inert page for free) ──
function openDialog(title, content) {
    closeDialog();
    const opener = document.activeElement;
    const titleId = "dialog-title";
    const dlg = el("dialog", {class: "sheet", "aria-labelledby": titleId}, [
        el("div", {class: "sheet-inner"}, [
            el("div", {class: "sheet-head"}, [
                el("h2", {class: "h-panel", id: titleId}, title),
                el("button", {class: "icon-btn", type: "button", "aria-label": "Close",
                    onclick: () => dlg.close()}, [icon(ICONS.close)]),
            ]),
            el("div", {class: "sheet-body"}, [].concat(content)),
        ]),
    ]);
    // A click on the dialog element itself (not .sheet-inner) is the backdrop.
    dlg.addEventListener("click", e => {
        if (e.target === dlg) dlg.close();
    });
    dlg.addEventListener("close", () => {
        dlg.remove();
        // After a save the opener row has been re-rendered away; fall back
        // to the view so keyboard users aren't dropped at the top of <body>.
        if (opener?.isConnected) opener.focus();
        else Shell.outlet?.focus({preventScroll: true});
    });
    document.body.appendChild(dlg);
    if (dlg.showModal) dlg.showModal();
    else dlg.setAttribute("open", "");
}

function closeDialog() {
    document.querySelectorAll("dialog.sheet").forEach(d => d.open ? d.close() : d.remove());
}

// ── Service worker (skipped in demo mode so fixtures never get cached) ──
if ("serviceWorker" in navigator && !DEMO) {
    window.addEventListener("load", () => {
        navigator.serviceWorker.register("./sw.js").catch(err =>
            console.warn("Service worker registration failed:", err));
    });
}

void boot();
