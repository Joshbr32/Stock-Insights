// app.js — main app: views, routing, event handling.
//
// No framework. The whole UI is rendered by string-templating into a
// single <main id="view"> outlet, then re-rendered on tab switches or
// data changes. Touch targets are ≥44px; numbers always render with
// tabular figures so columns align.

import {Api} from "./api.js";
import {
    buildEquityCurve,
    computeAnalytics,
    computeGoalProgress,
    computeHoldings,
    computePortfolio,
    filterTradesByDateRange,
    isClosed,
    normalizeTrade,
    realizedBySymbol,
    tradeProfit,
    tradeStatus,
} from "./portfolio.js";

// ── Global state (kept tiny — re-fetched as needed) ───────────────────
const State = {
    accounts: [],            // [{name, goal_target, goal_presets, position}]
    trades: [],              // normalized trade objects
    goalGroup: null,         // {account_names, shared_goal}
    watchlist: [],           // [symbol, ...]
    marks: {},               // {symbol: price}
    selectedAccount: "All",  // 'All' | account name
    view: "portfolio",       // 'portfolio' | 'trades' | 'goals' | 'watchlist'
    // Date-range filter — applied to the analytics card on the
    // portfolio view and to the trade list on the trades view.
    // Persisted to localStorage so the filter "sticks" across reloads
    // (matches the desktop's per-account persistence intent).
    dateRangeKey: localStorage.getItem("date_range_key") || "all",
};

// Human-friendly labels for the date-range keys. Mirrors
// TradesTable.qml's _rangeLabel() on desktop so the on-screen wording
// reads the same.
const DATE_RANGE_LABELS = {
    all: "All time",
    week: "This week",
    month: "This month",
    "30d": "Last 30 days",
    ytd: "Year to date",
};

function setDateRange(key) {
    if (!DATE_RANGE_LABELS[key]) key = "all";
    State.dateRangeKey = key;
    localStorage.setItem("date_range_key", key);
    // Re-render the active view; analytics on the portfolio tab and
    // the trade list on the trades tab both consume this state.
    renderView();
}

// ── Tiny DOM helpers ──────────────────────────────────────────────────
const $ = sel => document.querySelector(sel);
const el = (tag, attrs = {}, children = []) => {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
        if (k === "class") node.className = v;
        else if (k === "html") node.innerHTML = v;
        else if (k.startsWith("on") && typeof v === "function") {
            node.addEventListener(k.slice(2), v);
        } else if (v !== false && v != null) node.setAttribute(k, v);
    }
    for (const c of [].concat(children)) {
        if (c == null || c === false) continue;
        node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    }
    return node;
};

// ── Number formatting (tabular, currency, deltas) ─────────────────────
const usd = new Intl.NumberFormat("en-US", {
    style: "currency", currency: "USD", maximumFractionDigits: 2,
});
const usdCompact = new Intl.NumberFormat("en-US", {
    style: "currency", currency: "USD", notation: "compact",
    maximumFractionDigits: 1,
});
const pct = (v, digits = 2) => v == null ? "—" : `${v.toFixed(digits)}%`;
const fmtMoney = v => v == null ? "—" : usd.format(v);
const fmtCompact = v => v == null ? "—" : usdCompact.format(v);
const fmtNum = (v, digits = 2) => v == null ? "—" : Number(v).toFixed(digits);

const deltaClass = v => v == null ? "" : v > 0.005 ? "gain" : v < -0.005 ? "loss" : "";
const signed = v => v == null ? "—" : (v >= 0 ? "+" : "") + usd.format(v);

// ── Toast messages ────────────────────────────────────────────────────
function toast(msg, kind = "info") {
    const box = $("#toast");
    box.textContent = msg;
    box.className = `toast ${kind} show`;
    setTimeout(() => box.classList.remove("show"), 2400);
}

// ── Top-level boot ────────────────────────────────────────────────────
async function boot() {
    if (!Api.isAuthed()) {
        renderLogin();
        return;
    }
    try {
        await loadAll();
        renderShell();
    } catch (err) {
        if (err.code === 401) {
            renderLogin();
        } else {
            renderLogin(err.message);
        }
    }
}

async function loadAll() {
    const [accts, rawTrades, gg, wl] = await Promise.all([
        Api.getAccounts(),
        Api.getTrades(),
        Api.getGoalGroup(),
        Api.getWatchlist(),
    ]);
    State.accounts = accts;
    State.trades = rawTrades.map(normalizeTrade);
    State.goalGroup = gg;
    State.watchlist = wl;
    await refreshMarks();
}

async function refreshMarks() {
    const symbols = new Set(State.watchlist);
    for (const t of State.trades) {
        if (!isClosed(t) && !t.is_pending && t.instrument) symbols.add(t.instrument);
    }
    if (symbols.size === 0) {
        State.marks = {};
        return;
    }
    try {
        State.marks = await Api.getQuotes([...symbols]);
    } catch (err) {
        console.warn("Quote fetch failed:", err);
        toast("Couldn't fetch live prices", "warn");
    }
}

// ── Login screen ──────────────────────────────────────────────────────
function renderLogin(errorMsg = "") {
    document.body.innerHTML = "";
    // Friendly host display: strip protocol + trailing slash so the eyebrow
    // line reads as a server name, not a URL.
    const hostHint = Api.getServer().replace(/^https?:\/\//, "");

    const box = el("section", {class: "login"}, [
        el("div", {class: "login-mast"}, [
            el("div", {class: "mast-eyebrow"}, "Portfolio Edition"),
            el("h1", {class: "mast-title"}, [
                "Stock", el("em", {}, "Insights"),
            ]),
            el("div", {class: "mast-rule"}),
        ]),
        el("form", {
            class: "login-form",
            onsubmit: async e => {
                e.preventDefault();
                const u = $("#usr").value.trim();
                const p = $("#pwd").value;
                if (!u || !p) return;
                $("#login-btn").disabled = true;
                $("#login-btn").textContent = "Connecting…";
                try {
                    await Api.login(u, p);
                    await loadAll();
                    renderShell();
                } catch (err) {
                    $("#login-err").textContent = err.message || "Login failed";
                    $("#login-btn").disabled = false;
                    $("#login-btn").textContent = "Sign in";
                }
            }
        }, [
            el("label", {}, [
                el("span", {}, "Username"),
                el("input", {
                    id: "usr", type: "text", required: true,
                    autocomplete: "username", autocapitalize: "none",
                    value: Api.getUser()?.username || "",
                }),
            ]),
            el("label", {}, [
                el("span", {}, "Password"),
                el("input", {
                    id: "pwd", type: "password", required: true,
                    autocomplete: "current-password",
                }),
            ]),
            el("div", {id: "login-err", class: "form-err"}, errorMsg),
            el("button", {id: "login-btn", type: "submit", class: "btn-primary"}, "Sign in"),
            el("p", {class: "login-foot"}, [
                "Connecting to ",
                el("span", {class: "login-host"}, hostHint),
                ". Sessions last 30 days.",
            ]),
        ]),
    ]);
    document.body.appendChild(box);
}

// ── App shell (header + view + bottom nav) ────────────────────────────
function renderShell() {
    document.body.innerHTML = "";
    document.body.appendChild(el("div", {class: "app-shell"}, [
        renderHeader(),
        el("main", {id: "view", class: "view"}),
        renderTabs(),
    ]));
    document.body.appendChild(el("div", {id: "toast", class: "toast"}));
    // Modal mount point
    document.body.appendChild(el("div", {id: "modal-root"}));
    renderView();
}

function renderHeader() {
    const user = Api.getUser();
    return el("header", {class: "topbar"}, [
        el("div", {class: "topbar-left"}, [
            el("div", {class: "brand"}, [
                "Stock", el("em", {}, "Insights"),
            ]),
            el("div", {class: "user-line"}, user ? `@${user.username}` : ""),
        ]),
        el("div", {class: "topbar-right"}, [
            // Account selector — affects Portfolio + Trades
            renderAccountPill(),
            el("button", {
                class: "icon-btn", title: "Refresh",
                onclick: async () => {
                    $("#refresh-icon").classList.add("spin");
                    try {
                        await loadAll();
                        renderView();
                        toast("Refreshed", "ok");
                    } catch (e) {
                        toast(e.message || "Refresh failed", "err");
                    }
                    $("#refresh-icon")?.classList.remove("spin");
                }
            }, [el("span", {id: "refresh-icon", class: "icon"}, "↻")]),
            el("button", {
                class: "icon-btn", title: "Sign out",
                onclick: async () => {
                    await Api.logout();
                    renderLogin();
                }
            }, [el("span", {class: "icon"}, "↪")]),
        ]),
    ]);
}

function renderAccountPill() {
    const options = ["All", ...State.accounts.map(a => a.name)];
    return el("div", {class: "acct-pill"}, [
        el("select", {
            id: "acct-select",
            onchange: e => {
                State.selectedAccount = e.target.value;
                renderView();
            }
        }, options.map(name => el("option", {
            value: name, selected: name === State.selectedAccount ? "selected" : false,
        }, name))),
    ]);
}

function renderTabs() {
    const tabs = [
        {id: "portfolio", label: "Portfolio", glyph: "▦"},
        {id: "trades", label: "Trades", glyph: "≡"},
        {id: "goals", label: "Goals", glyph: "◎"},
        {id: "watchlist", label: "Watchlist", glyph: "★"},
    ];
    return el("nav", {class: "tabs"},
        tabs.map(t => el("button", {
            class: "tab" + (State.view === t.id ? " active" : ""),
            onclick: () => {
                State.view = t.id;
                renderView();
            },
        }, [
            el("span", {class: "tab-glyph"}, t.glyph),
            el("span", {class: "tab-label"}, t.label),
        ]))
    );
}

function renderView() {
    const outlet = $("#view");
    if (!outlet) return;
    outlet.innerHTML = "";
    switch (State.view) {
        case "portfolio":
            outlet.appendChild(viewPortfolio());
            break;
        case "trades":
            outlet.appendChild(viewTrades());
            break;
        case "goals":
            outlet.appendChild(viewGoals());
            break;
        case "watchlist":
            outlet.appendChild(viewWatchlist());
            break;
    }
}

// ── View: Portfolio ───────────────────────────────────────────────────
function tradesForSelected() {
    if (State.selectedAccount === "All") return State.trades;
    return State.trades.filter(t => t.account === State.selectedAccount);
}

function viewPortfolio() {
    const trades = tradesForSelected();
    const holdings = computeHoldings(trades);
    const realizedMap = realizedBySymbol(trades);
    const {rows, summary} = computePortfolio(holdings, State.marks, realizedMap);

    const wrap = el("div", {class: "stack"});

    // Big number masthead
    wrap.appendChild(el("section", {class: "masthead"}, [
        el("div", {class: "mast-eyebrow"}, State.selectedAccount === "All"
            ? "Combined value" : `${State.selectedAccount} · Market value`),
        el("h2", {class: "big-number " + deltaClass(summary.total_pl)},
            fmtMoney(summary.market_value)),
        el("div", {class: "big-sub " + deltaClass(summary.total_pl)}, [
            `${signed(summary.total_pl)} total`,
            el("span", {class: "muted"}, ` · ${pct(summary.return_pct)}`),
        ]),
    ]));

    // Stat grid
    wrap.appendChild(el("section", {class: "stat-grid"}, [
        statCard("Realized", signed(summary.realized_pl), deltaClass(summary.realized_pl)),
        statCard("Unrealized", signed(summary.unrealized_pl), deltaClass(summary.unrealized_pl)),
        statCard("Cost basis", fmtCompact(summary.cost_basis)),
        statCard("Positions", String(summary.positions)),
    ]));

    // Holdings table (always shows ALL open positions — holdings are
    // by-definition a "right now" snapshot, so the date-range filter
    // deliberately doesn't touch them. Same intent as desktop's
    // PortfolioView, where HoldingsTable ignores AccountController.dateRangeKey.)
    wrap.appendChild(el("section", {class: "card"}, [
        el("div", {class: "card-head"}, [
            el("h3", {}, "Holdings"),
            el("span", {class: "card-meta"}, `${rows.length} symbol${rows.length === 1 ? "" : "s"}`),
        ]),
        rows.length === 0
            ? el("p", {class: "empty"}, "No open positions.")
            : holdingsTable(rows),
    ]));

    // Date-range filter — applies to the equity curve + analytics
    // below. Holdings stay unfiltered (above). Matches the desktop's
    // AnalyticsPanel layout, where the same combo box drives both the
    // analytics metrics and the Trade History list.
    const rangedTrades = filterTradesByDateRange(trades, State.dateRangeKey);

    wrap.appendChild(el("section", {class: "range-bar"}, [
        el("span", {class: "range-bar-caption"},
            `Analytics window: ${DATE_RANGE_LABELS[State.dateRangeKey] || "All time"}`),
        rangePicker(),
    ]));

    // Equity curve — built from the date-filtered closed trades.
    wrap.appendChild(equityCurveCard(buildEquityCurve(rangedTrades)));

    // Trade analytics — computed over the date-filtered set.
    const an = computeAnalytics(rangedTrades);
    wrap.appendChild(el("section", {class: "card"}, [
        el("div", {class: "card-head"}, [el("h3", {}, "Trade analytics")]),
        el("div", {class: "kv"}, [
            kvRow("Closed trades", String(an.closed_trades)),
            kvRow("Open trades", String(an.open_trades)),
            kvRow("Win rate", pct(an.win_rate_pct, 1)),
            kvRow("Avg win", signed(an.avg_win)),
            kvRow("Avg loss", signed(an.avg_loss)),
            kvRow("Best trade", signed(an.best_trade)),
            kvRow("Worst trade", signed(an.worst_trade)),
            kvRow("Profit factor",
                an.profit_factor === Infinity ? "∞"
                    : an.profit_factor == null ? "—" : an.profit_factor.toFixed(2)),
        ]),
    ]));

    return wrap;
}

function statCard(label, value, klass = "") {
    return el("div", {class: "stat"}, [
        el("div", {class: "stat-label"}, label),
        el("div", {class: "stat-value " + klass}, value),
    ]);
}

function kvRow(label, value) {
    return el("div", {class: "kv-row"}, [
        el("span", {class: "kv-label"}, label),
        el("span", {class: "kv-value"}, value),
    ]);
}

// ── Date-range picker (shared by viewPortfolio + viewTrades) ──────────
function rangePicker() {
    const sel = el("select", {
        class: "range-picker",
        onchange: e => setDateRange(e.target.value),
    });
    for (const [key, label] of Object.entries(DATE_RANGE_LABELS)) {
        const opt = el("option", {value: key}, label);
        if (key === State.dateRangeKey) opt.selected = true;
        sel.appendChild(opt);
    }
    return el("label", {class: "range-picker-wrap"}, [
        el("span", {class: "range-picker-label"}, "Range"),
        sel,
    ]);
}

// ── Equity-curve card ─────────────────────────────────────────────────
//
// Mirrors EquityCurveCard.qml on desktop. The chart is a hand-rolled
// SVG (no Chart.js dep) — keeps the PWA payload tiny and the rendering
// CSS-themable. Shape:
//   • 320×140 viewBox, polyline auto-scaled to the data range
//   • 5% vertical padding so the line never touches the top/bottom
//   • horizontal mid-line through y = 0 when the curve crosses zero
//   • points are spaced by their true close_date (epoch ms), so a
//     trade cluster looks like a cluster — not evenly spaced ticks
function equityCurveCard(curve) {
    if (!curve || curve.length === 0) {
        return el("section", {class: "card equity-card"}, [
            el("div", {class: "card-head"}, [el("h3", {}, "Equity curve")]),
            el("p", {class: "empty"},
                "No closed trades yet — close a trade to see the curve."),
        ]);
    }

    const xs = curve.map(p => p.x);
    const ys = curve.map(p => p.y);
    const xMin = Math.min(...xs), xMax = Math.max(...xs);
    const yMin = Math.min(0, ...ys), yMax = Math.max(0, ...ys);
    const ySpan = Math.max(1, yMax - yMin);
    const xSpan = Math.max(1, xMax - xMin);

    const W = 320, H = 140, PADX = 4, PADY = 8;
    const usableW = W - PADX * 2, usableH = H - PADY * 2;
    // Note `H - PADY` because SVG y grows downward; we invert so a
    // higher P/L sits visually higher.
    const sx = x => PADX + ((x - xMin) / xSpan) * usableW;
    const sy = y => (H - PADY) - ((y - yMin) / ySpan) * usableH;

    const points = curve.map(p => `${sx(p.x).toFixed(1)},${sy(p.y).toFixed(1)}`).join(" ");

    // Zero baseline — only drawn if the curve goes both positive and
    // negative, otherwise it'd just sit at the bottom edge.
    const zeroLine = (yMin < 0 && yMax > 0)
        ? `<line x1="${PADX}" x2="${W - PADX}" y1="${sy(0)}" y2="${sy(0)}" class="equity-zero"/>`
        : "";

    // Final-point marker — small dot at the latest cumulative P/L so
    // the most recent value is visually anchored.
    const lastX = sx(xs[xs.length - 1]), lastY = sy(ys[ys.length - 1]);
    const dot = `<circle cx="${lastX.toFixed(1)}" cy="${lastY.toFixed(1)}" r="3.5" class="equity-dot"/>`;

    const realized = ys[ys.length - 1];
    // Reuse curve.length - 1 because the curve is seeded with a zero
    // point one day before the first close (see buildEquityCurve), so
    // (length - 1) is the actual closed-trade count.
    const tradeCount = curve.length - 1;

    return el("section", {class: "card equity-card"}, [
        el("div", {class: "card-head"}, [
            el("h3", {}, "Equity curve"),
            el("span", {class: "card-meta"},
                `${signed(realized)} · ${tradeCount} trade${tradeCount === 1 ? "" : "s"}`),
        ]),
        el("div", {
            class: "equity-svg-wrap",
            html: `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" class="equity-svg">
                ${zeroLine}
                <polyline points="${points}" class="equity-line"/>
                ${dot}
            </svg>`,
        }),
    ]);
}

function holdingsTable(rows) {
    const head = el("div", {class: "tr head"}, [
        el("span", {class: "td sym"}, "Symbol"),
        el("span", {class: "td num"}, "Qty"),
        el("span", {class: "td num"}, "Mark"),
        el("span", {class: "td num"}, "P/L"),
    ]);
    const body = rows.map(r => el("div", {
        class: "tr",
        onclick: () => showHoldingDetail(r),
    }, [
        el("span", {class: "td sym"}, [
            el("strong", {}, r.instrument),
            r.qty < 0 ? el("em", {class: "tag-short"}, "SHORT") : null,
        ]),
        el("span", {class: "td num"}, String(Math.abs(r.qty))),
        el("span", {class: "td num"}, fmtNum(r.mark)),
        el("span", {class: "td num " + deltaClass(r.total_pl)}, signed(r.total_pl)),
    ]));
    return el("div", {class: "table"}, [head, ...body]);
}

function showHoldingDetail(r) {
    openModal(`${r.instrument}`, el("div", {class: "kv"}, [
        kvRow("Quantity", String(Math.abs(r.qty)) + (r.qty < 0 ? " (short)" : "")),
        kvRow("Avg cost", fmtNum(r.avg_cost)),
        kvRow("Mark", fmtNum(r.mark)),
        kvRow("Market value", fmtMoney(r.market_value)),
        kvRow("Weight", pct(r.weight_pct, 1)),
        kvRow("Unrealized P/L", signed(r.unrealized_pl)),
        kvRow("Realized P/L", signed(r.realized_pl)),
        kvRow("Total P/L", signed(r.total_pl)),
        r.notes ? el("div", {class: "kv-row"}, [
            el("span", {class: "kv-label"}, "Notes"),
            el("span", {class: "kv-value notes"}, r.notes),
        ]) : null,
    ]));
}

// ── View: Trades ──────────────────────────────────────────────────────
function viewTrades() {
    // Apply the date-range filter BEFORE reversing so the filter
    // semantics match the analytics on the portfolio view exactly
    // (same set of trades, just displayed newest-first here).
    const all = tradesForSelected();
    const ranged = filterTradesByDateRange(all, State.dateRangeKey);
    const trades = ranged.slice().reverse();  // newest first by id

    const wrap = el("div", {class: "stack"});
    wrap.appendChild(el("section", {class: "section-head"}, [
        el("h2", {}, "Trades"),
        el("button", {
            class: "btn-primary compact",
            onclick: () => openTradeEditor(null),
        }, "+ New trade"),
    ]));

    // Range picker — same control as on the portfolio view, sharing
    // State.dateRangeKey, so toggling here also affects analytics there.
    wrap.appendChild(el("section", {class: "range-bar"}, [
        el("span", {class: "range-bar-caption"},
            `${ranged.length} of ${all.length} ${all.length === 1 ? "trade" : "trades"}`
            + ` · ${DATE_RANGE_LABELS[State.dateRangeKey] || "All time"}`),
        rangePicker(),
    ]));

    if (trades.length === 0) {
        wrap.appendChild(el("p", {class: "empty card"},
            State.dateRangeKey === "all"
                ? "No trades yet."
                : "No trades in the selected range."));
        return wrap;
    }

    const list = el("div", {class: "trade-list"});
    for (const t of trades) {
        const profit = tradeProfit(t);
        const status = tradeStatus(t);
        list.appendChild(el("button", {
            class: "trade-row",
            onclick: () => openTradeEditor(t),
        }, [
            el("div", {class: "tr-l"}, [
                el("div", {class: "tr-sym"}, [
                    el("strong", {}, t.instrument || "—"),
                    el("span", {class: "tag tag-" + status.toLowerCase()}, status),
                ]),
                el("div", {class: "tr-meta"}, [
                    `${t.share_count} sh @ ${fmtNum(t.buy_price)}`,
                    t.account ? el("span", {class: "muted"}, ` · ${t.account}`) : null,
                ]),
            ]),
            el("div", {class: "tr-r"}, [
                el("div", {class: "tr-pl " + deltaClass(profit)},
                    profit == null ? "—" : signed(profit)),
                el("div", {class: "tr-date muted"},
                    t.close_date || t.open_date || ""),
            ]),
        ]));
    }
    wrap.appendChild(list);
    return wrap;
}

// ── Trade editor (modal) ──────────────────────────────────────────────
function openTradeEditor(existing) {
    const accountOptions = State.accounts.map(a => a.name);
    if (accountOptions.length === 0) {
        toast("Create an account on the desktop app first", "warn");
        return;
    }
    const t = existing ? {...existing} : {
        account: State.selectedAccount === "All" ? accountOptions[0] : State.selectedAccount,
        instrument: "", share_count: 0, buy_price: 0,
        sell_price: null, open_date: new Date().toISOString().slice(0, 10),
        close_date: null, notes: "", is_pending: false, is_short: false,
    };

    const form = el("form", {
        class: "trade-form",
        onsubmit: async e => {
            e.preventDefault();
            await saveTradeFromForm(existing, form);
        }
    }, [
        formRow("Account", el("select", {name: "account", required: true},
            accountOptions.map(n => el("option", {
                value: n, selected: n === t.account ? "selected" : false,
            }, n)))),

        formRow("Symbol", el("input", {
            name: "instrument", required: true, autocapitalize: "characters",
            value: t.instrument, placeholder: "AAPL",
        })),

        el("div", {class: "form-grid-2"}, [
            formRow("Shares", el("input", {
                name: "share_count", type: "number", inputmode: "numeric",
                min: "1", required: true, value: t.share_count || "",
            })),
            formRow(t.is_short ? "Short price" : "Buy price", el("input", {
                name: "buy_price", type: "number", inputmode: "decimal",
                step: "0.01", min: "0", required: true, value: t.buy_price || "",
            })),
        ]),

        el("div", {class: "form-grid-2"}, [
            formRow("Open date", el("input", {
                name: "open_date", type: "date", value: t.open_date || "",
            })),
            formRow("Close date", el("input", {
                name: "close_date", type: "date", value: t.close_date || "",
            })),
        ]),

        formRow(t.is_short ? "Cover price (close)" : "Sell price (close)",
            el("input", {
                name: "sell_price", type: "number", inputmode: "decimal",
                step: "0.01", min: "0", value: t.sell_price ?? "",
                placeholder: "Leave blank if open",
            })),

        el("div", {class: "checkboxes"}, [
            el("label", {class: "check"}, [
                el("input", {
                    type: "checkbox", name: "is_short",
                    checked: t.is_short ? "checked" : false,
                }),
                el("span", {}, "Short position"),
            ]),
            el("label", {class: "check"}, [
                el("input", {
                    type: "checkbox", name: "is_pending",
                    checked: t.is_pending ? "checked" : false,
                }),
                el("span", {}, "Pending (not yet filled)"),
            ]),
        ]),

        formRow("Notes", el("textarea", {
            name: "notes", rows: 2,
            placeholder: "Optional",
        }, t.notes || "")),

        el("div", {class: "form-actions"}, [
            existing
                ? el("button", {
                    type: "button", class: "btn-danger",
                    onclick: () => deleteTrade(existing),
                }, "Delete")
                : el("span"),
            el("button", {type: "submit", class: "btn-primary"},
                existing ? "Save changes" : "Add trade"),
        ]),
    ]);

    openModal(existing ? "Edit trade" : "New trade", form);
}

async function saveTradeFromForm(existing, form) {
    const fd = new FormData(form);
    const incoming = {
        instrument: String(fd.get("instrument")).trim().toUpperCase(),
        share_count: Number(fd.get("share_count")),
        buy_price: Number(fd.get("buy_price")),
        sell_price: fd.get("sell_price") === "" ? null : Number(fd.get("sell_price")),
        open_date: fd.get("open_date") || null,
        close_date: fd.get("close_date") || null,
        notes: String(fd.get("notes") || ""),
        is_pending: fd.get("is_pending") === "on",
        is_short: fd.get("is_short") === "on",
    };
    const targetAccount = String(fd.get("account"));

    // Replace-account-trades is the only write API. Build the new array for
    // that account from current state, then POST it back.
    const submitBtn = form.querySelector("button[type=submit]");
    submitBtn.disabled = true;
    submitBtn.textContent = "Saving…";

    try {
        // Special case: if the trade is moving accounts, we have to PUT both.
        const movedAccounts = new Set([targetAccount]);
        if (existing && existing.account && existing.account !== targetAccount) {
            movedAccounts.add(existing.account);
        }

        for (const acctName of movedAccounts) {
            let acctTrades = State.trades.filter(t => t.account === acctName);
            if (existing) {
                acctTrades = acctTrades.filter(t => t.id !== existing.id);
            }
            if (acctName === targetAccount) {
                acctTrades.push({account: targetAccount, ...incoming});
            }
            const payload = acctTrades.map(t => ({
                instrument: t.instrument,
                share_count: t.share_count,
                buy_price: t.buy_price,
                sell_price: t.sell_price,
                open_date: t.open_date,
                close_date: t.close_date,
                notes: t.notes,
                is_pending: t.is_pending,
                is_short: t.is_short,
            }));
            await Api.replaceAccountTrades(acctName, payload);
        }

        closeModal();
        await loadAll();
        renderView();
        toast(existing ? "Trade updated" : "Trade added", "ok");
    } catch (err) {
        toast(err.message || "Save failed", "err");
        submitBtn.disabled = false;
        submitBtn.textContent = existing ? "Save changes" : "Add trade";
    }
}

async function deleteTrade(existing) {
    if (!confirm(`Delete this ${existing.instrument} trade?`)) return;
    try {
        const remaining = State.trades
            .filter(t => t.account === existing.account && t.id !== existing.id)
            .map(t => ({
                instrument: t.instrument, share_count: t.share_count,
                buy_price: t.buy_price, sell_price: t.sell_price,
                open_date: t.open_date, close_date: t.close_date,
                notes: t.notes, is_pending: t.is_pending, is_short: t.is_short,
            }));
        await Api.replaceAccountTrades(existing.account, remaining);
        closeModal();
        await loadAll();
        renderView();
        toast("Trade deleted", "ok");
    } catch (err) {
        toast(err.message || "Delete failed", "err");
    }
}

function formRow(label, input) {
    return el("label", {class: "form-row"}, [
        el("span", {class: "form-label"}, label),
        input,
    ]);
}

// ── View: Goals ───────────────────────────────────────────────────────
function viewGoals() {
    const wrap = el("div", {class: "stack"});

    // Shared (group) goal
    const groupAccts = State.goalGroup?.account_names || [];
    const sharedTarget = State.goalGroup?.shared_goal || 0;
    const sharedTrades = State.trades.filter(t => groupAccts.includes(t.account));
    const sharedHoldings = computeHoldings(sharedTrades);
    const sharedRMap = realizedBySymbol(sharedTrades);
    const {summary: sharedSummary} = computePortfolio(sharedHoldings, State.marks, sharedRMap);
    const sharedProgress = computeGoalProgress(sharedTrades, sharedTarget);

    if (groupAccts.length > 0) {
        wrap.appendChild(goalCard({
            label: "Shared goal · " + groupAccts.join(" + "),
            target: sharedTarget,
            realized: sharedProgress.realized,
            total: sharedSummary.total_pl,
            progress: sharedProgress,
        }));
    }

    // Per-account goals
    for (const a of State.accounts) {
        const target = a.goal_target || 0;
        if (target <= 0) continue;
        const acctTrades = State.trades.filter(t => t.account === a.name);
        const h = computeHoldings(acctTrades);
        const rMap = realizedBySymbol(acctTrades);
        const {summary} = computePortfolio(h, State.marks, rMap);
        const prog = computeGoalProgress(acctTrades, target);
        wrap.appendChild(goalCard({
            label: a.name,
            target,
            realized: prog.realized,
            total: summary.total_pl,
            progress: prog,
        }));
    }

    if (wrap.children.length === 0) {
        wrap.appendChild(el("p", {class: "empty card"},
            "No goal targets set. Configure in the desktop app."));
    }

    return wrap;
}

function goalCard({label, target, realized, total, progress}) {
    const pctReal = target > 0 ? Math.min(100, (realized / target) * 100) : 0;
    const pctTotal = target > 0 ? Math.min(100, (total / target) * 100) : 0;
    const klass = total >= target ? "gain" : "";

    return el("section", {class: "card goal-card"}, [
        el("div", {class: "goal-label"}, label),
        el("div", {class: "goal-amount " + klass}, fmtMoney(total)),
        el("div", {class: "goal-target muted"}, `of ${fmtMoney(target)} target`),
        el("div", {class: "progress"}, [
            el("div", {class: "progress-fill total", style: `width:${pctTotal}%`}),
            el("div", {class: "progress-fill realized", style: `width:${pctReal}%`}),
        ]),
        el("div", {class: "progress-legend"}, [
            el("span", {}, [el("i", {class: "swatch realized"}), `Realized ${pct(pctReal, 0)}`]),
            el("span", {}, [el("i", {class: "swatch total"}), `Total ${pct(pctTotal, 0)}`]),
        ]),
        el("div", {class: "kv"}, [
            kvRow("Remaining to goal", fmtMoney(progress.remaining_profit)),
            kvRow("Per month needed", fmtMoney(progress.monthly_to_goal)),
            kvRow("Per week needed", fmtMoney(progress.weekly_to_goal)),
            kvRow("Per day needed", fmtMoney(progress.daily_to_goal)),
            kvRow("Avg daily realized",
                progress.avg_daily == null ? "—" : signed(progress.avg_daily)),
            kvRow("Trading days left", String(progress.days_remaining)),
        ]),
    ]);
}

// ── View: Watchlist ───────────────────────────────────────────────────
function viewWatchlist() {
    const wrap = el("div", {class: "stack"});
    wrap.appendChild(el("section", {class: "section-head"}, [
        el("h2", {}, "Watchlist"),
        el("button", {
            class: "btn-primary compact",
            onclick: () => addWatchSymbol(),
        }, "+ Add"),
    ]));

    if (State.watchlist.length === 0) {
        wrap.appendChild(el("p", {class: "empty card"},
            "Your watchlist is empty."));
        return wrap;
    }

    const list = el("div", {class: "watch-list"});
    for (const sym of State.watchlist) {
        const price = State.marks[sym];
        list.appendChild(el("div", {class: "watch-row"}, [
            el("div", {class: "watch-sym"}, sym),
            el("div", {class: "watch-price"},
                price == null ? el("span", {class: "muted"}, "—") : fmtNum(price)),
            el("button", {
                class: "icon-btn small",
                title: "Remove",
                onclick: async () => removeWatchSymbol(sym),
            }, "✕"),
        ]));
    }
    wrap.appendChild(list);
    return wrap;
}

async function addWatchSymbol() {
    const sym = prompt("Add symbol:");
    if (!sym) return;
    const clean = sym.trim().toUpperCase();
    if (!clean || State.watchlist.includes(clean)) return;
    const next = [...State.watchlist, clean];
    try {
        await Api.setWatchlist(next);
        State.watchlist = next;
        await refreshMarks();
        renderView();
        toast(`Added ${clean}`, "ok");
    } catch (err) {
        toast(err.message || "Add failed", "err");
    }
}

async function removeWatchSymbol(sym) {
    const next = State.watchlist.filter(s => s !== sym);
    try {
        await Api.setWatchlist(next);
        State.watchlist = next;
        renderView();
    } catch (err) {
        toast(err.message || "Remove failed", "err");
    }
}

// ── Modal ─────────────────────────────────────────────────────────────
function openModal(title, content) {
    closeModal();
    const root = $("#modal-root");
    const sheet = el("div", {class: "modal-sheet", onclick: e => e.stopPropagation()}, [
        el("div", {class: "modal-head"}, [
            el("h3", {}, title),
            el("button", {class: "icon-btn", onclick: closeModal}, "✕"),
        ]),
        el("div", {class: "modal-body"}, content),
    ]);
    const overlay = el("div", {class: "modal-overlay", onclick: closeModal}, [sheet]);
    root.appendChild(overlay);
    requestAnimationFrame(() => overlay.classList.add("show"));
}

function closeModal() {
    const root = $("#modal-root");
    if (!root) return;
    root.innerHTML = "";
}

// ── PWA service-worker registration ───────────────────────────────────
if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
        navigator.serviceWorker.register("./sw.js").catch(err =>
            console.warn("SW registration failed:", err));
    });
}

// ── Go ────────────────────────────────────────────────────────────────
boot();
