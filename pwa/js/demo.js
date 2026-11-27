// demo.js — offline demo mode for design review (open the app with ?demo).
//
// Replaces the Api object's methods with in-memory fixtures so every view
// renders without a server or network. Loaded only by app.js when the
// URL has ?demo, so it costs nothing in normal use; it is not in the
// service worker's precache list on purpose. Nothing here is persisted.
//
// ?demo         a server 1.1 (per-trade PUT/DELETE /trades/{account}/{uid})
// ?demo=legacy  a pre-1.1 server: the per-trade routes answer 404, so the
//               app falls back to whole-account saves
// ?demo=offline quotes fail;  ?demo=login  starts signed out

import {newTradeUid} from "./portfolio.js";

const SYMBOLS = {AAPL: 228.4, MSFT: 431.2, NVDA: 142.7, AMD: 151.3, TSLA: 248.9, SHOP: 101.5, COST: 902.1, PLTR: 61.8};

function isoDaysAgo(n) {
    const d = new Date();
    d.setDate(d.getDate() - n);
    return d.toLocaleDateString("en-CA");
}

function fixtureTrades() {
    const out = [];
    let id = 1;
    const accounts = ["Main", "Roth", "Swing"];
    const syms = Object.keys(SYMBOLS);
    // Deterministic pseudo-random so screenshots are reproducible.
    let seed = 7;
    const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
    for (let i = 0; i < 46; i++) {
        const sym = syms[i % syms.length];
        const base = SYMBOLS[sym];
        const open = 320 - i * 7;
        const buy = +(base * (0.82 + rnd() * 0.2)).toFixed(2);
        const win = rnd() < 0.62;
        const sell = +(buy * (win ? 1.02 + rnd() * 0.1 : 0.93 + rnd() * 0.05)).toFixed(2);
        out.push({
            id: id++, uid: newTradeUid(), account: accounts[i % 3], instrument: sym,
            share_count: 5 + Math.floor(rnd() * 40), buy_price: buy, sell_price: sell,
            open_date: isoDaysAgo(open), close_date: isoDaysAgo(Math.max(1, open - 5 - Math.floor(rnd() * 20))),
            notes: i === 3 ? "Earnings run-up <b>not markup</b>" : "", tag: i % 4 === 0 ? "swing" : i % 5 === 0 ? "earnings" : "",
            is_pending: false, is_short: false,
        });
    }
    // Open positions, one short, one pending.
    out.push({id: id++, uid: newTradeUid(), account: "Main", instrument: "NVDA", share_count: 30, buy_price: 128.4, sell_price: null,
        open_date: isoDaysAgo(20), close_date: null, notes: "Core position", tag: "", is_pending: false, is_short: false});
    out.push({id: id++, uid: newTradeUid(), account: "Swing", instrument: "TSLA", share_count: 10, buy_price: 262.0, sell_price: null,
        open_date: isoDaysAgo(6), close_date: null, notes: "", tag: "swing", is_pending: false, is_short: true});
    out.push({id: id++, uid: newTradeUid(), account: "Roth", instrument: "COST", share_count: 4, buy_price: 880.0, sell_price: null,
        open_date: isoDaysAgo(3), close_date: null, notes: "", tag: "", is_pending: false, is_short: false});
    out.push({id: id++, uid: newTradeUid(), account: "Main", instrument: "AMD", share_count: 25, buy_price: 140.0, sell_price: null,
        open_date: isoDaysAgo(1), close_date: null, notes: "Limit order", tag: "", is_pending: true, is_short: false});
    return out;
}

export function installDemo(Api) {
    const db = {
        accounts: [
            {name: "Main", goal_target: 12000, goal_presets: [], position: 0},
            {name: "Roth", goal_target: 5000, goal_presets: [], position: 1},
            {name: "Swing", goal_target: 0, goal_presets: [], position: 2},
        ],
        trades: fixtureTrades(),
        goalGroup: {account_names: ["Main", "Roth"], shared_goal: 20000},
        watchlist: ["AAPL", "MSFT", "SHOP", "PLTR"],
        user: {user_id: 1, username: "demo", is_admin: false},
        authed: true,
    };
    let nextId = 1000;
    const later = v => new Promise(r => setTimeout(() => r(structuredClone(v)), 120));
    const params = new URLSearchParams(location.search);
    const legacy = params.get("demo") === "legacy";
    // What api.js throws for a route an old server doesn't have.
    const notFound = () => Object.assign(new Error("Not Found"), {code: 404});

    Object.assign(Api, {
        getToken: () => (db.authed ? "demo" : null),
        getUser: () => db.user,
        isAuthed: () => db.authed && params.get("demo") !== "login",
        clearAuth: () => void (db.authed = false),
        async login(username) {
            db.authed = true;
            params.delete("demo");
            db.user = {...db.user, username};
            return later({token: "demo", ...db.user});
        },
        async logout() {
            db.authed = false;
        },
        getAccounts: () => later(db.accounts),
        saveAccounts: async names => void (db.accounts = names.map((n, i) =>
            db.accounts.find(a => a.name === n) || {name: n, goal_target: 0, goal_presets: [], position: i})),
        // A pre-1.1 server has no uid column.
        getTrades: () => later(legacy ? db.trades.map(({uid, ...t}) => t) : db.trades),
        async replaceAccountTrades(name, trades) {
            db.trades = db.trades.filter(t => t.account !== name)
                .concat(trades.map(t => ({...t, account: name, id: nextId++,
                    uid: legacy ? newTradeUid() : (t.uid || newTradeUid())})));
            return later(null);
        },
        async putTrade(name, trade) {
            if (legacy) throw notFound();
            const i = db.trades.findIndex(t => t.uid === trade.uid);
            const row = {...trade, account: name, id: i >= 0 ? db.trades[i].id : nextId++};
            if (i >= 0) db.trades[i] = row;
            else db.trades.push(row);
            if (!db.accounts.some(a => a.name === name)) {
                db.accounts.push({name, goal_target: 0, goal_presets: [], position: db.accounts.length});
            }
            return later({ok: true, uid: trade.uid});
        },
        async deleteTradeByUid(name, uid) {
            if (legacy) throw notFound();
            db.trades = db.trades.filter(t => !(t.uid === uid && t.account === name));
            return later({ok: true});
        },
        getGoalGroup: () => later(db.goalGroup),
        setGoalGroup: async (names, goal) => void (db.goalGroup = {account_names: names, shared_goal: goal}),
        getWatchlist: () => later(db.watchlist),
        setWatchlist: async s => void (db.watchlist = [...s]),
        async getQuotes(symbols) {
            if (params.get("demo") === "offline") throw new TypeError("Failed to fetch");
            const out = {};
            for (const s of symbols) {
                if (SYMBOLS[s]) out[s] = +(SYMBOLS[s] * (1 + (Math.random() - 0.5) * 0.004)).toFixed(2);
            }
            return later(out);
        },
    });
}
