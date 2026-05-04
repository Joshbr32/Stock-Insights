// api.js — thin fetch wrapper around the Stock Insights FastAPI backend.
//
// Token persistence: we stash the bearer token in localStorage. The server
// hands out 30-day tokens, so we don't need a refresh dance — if a call
// returns 401, we just bounce the user back to the login screen.

const TOKEN_KEY = "si.token";
const SERVER_KEY = "si.server";
const USER_KEY = "si.user";

export const Api = {
    // ── Server URL (user enters this on first run) ────────────────────────
    getServer() {
        return localStorage.getItem(SERVER_KEY) || "";
    },
    setServer(url) {
        localStorage.setItem(SERVER_KEY, url.replace(/\/+$/, ""));
    },

    // ── Auth state ────────────────────────────────────────────────────────
    getToken() {
        return localStorage.getItem(TOKEN_KEY);
    },
    getUser() {
        const raw = localStorage.getItem(USER_KEY);
        return raw ? JSON.parse(raw) : null;
    },
    isAuthed() {
        return !!this.getToken();
    },
    clearAuth() {
        localStorage.removeItem(TOKEN_KEY);
        localStorage.removeItem(USER_KEY);
    },

    // ── Core request helper ───────────────────────────────────────────────
    async _request(path, opts = {}) {
        const base = this.getServer();
        if (!base) throw new Error("No server URL configured");

        const headers = {"Content-Type": "application/json", ...(opts.headers || {})};
        const token = this.getToken();
        if (token && !opts.skipAuth) headers["Authorization"] = `Bearer ${token}`;

        const res = await fetch(base + path, {
            method: opts.method || "GET",
            headers,
            body: opts.body ? JSON.stringify(opts.body) : undefined,
        });

        if (res.status === 401 && !opts.skipAuth) {
            this.clearAuth();
            const err = new Error("Session expired");
            err.code = 401;
            throw err;
        }
        if (!res.ok) {
            let msg = `${res.status} ${res.statusText}`;
            try {
                const body = await res.json();
                if (body.detail) msg = body.detail;
            } catch (_) {
            }
            const err = new Error(msg);
            err.code = res.status;
            throw err;
        }
        if (res.status === 204) return null;
        return res.json();
    },

    // ── Auth ──────────────────────────────────────────────────────────────
    async login(username, password) {
        const data = await this._request("/auth/login", {
            method: "POST",
            body: {username, password},
            skipAuth: true,
        });
        localStorage.setItem(TOKEN_KEY, data.token);
        localStorage.setItem(USER_KEY, JSON.stringify({
            user_id: data.user_id, username: data.username, is_admin: data.is_admin,
        }));
        return data;
    },

    async logout() {
        try {
            await this._request("/auth/logout", {method: "POST"});
        } catch (_) {
        }
        this.clearAuth();
    },

    // ── Resource calls ────────────────────────────────────────────────────
    getAccounts() {
        return this._request("/accounts");
    },

    saveAccounts(accounts) {
        return this._request("/accounts", {method: "PUT", body: {accounts}});
    },

    getTrades() {
        return this._request("/trades");
    },

    /** Replace all trades for one account. trades[] uses the TradeIn schema. */
    replaceAccountTrades(accountName, trades) {
        return this._request(`/trades/${encodeURIComponent(accountName)}`, {
            method: "PUT",
            body: {account_name: accountName, trades},
        });
    },

    getGoalGroup() {
        return this._request("/goal-group");
    },

    setGoalGroup(account_names, shared_goal) {
        return this._request("/goal-group", {
            method: "PUT", body: {account_names, shared_goal},
        });
    },

    getWatchlist() {
        return this._request("/watchlist");
    },

    setWatchlist(symbols) {
        return this._request("/watchlist", {method: "PUT", body: {symbols}});
    },

    /** Live prices via the server-side /quotes patch. */
    async getQuotes(symbols) {
        const list = [...new Set(symbols.map(s => s.trim().toUpperCase()).filter(Boolean))];
        if (!list.length) return {};
        return this._request("/quotes?symbols=" + encodeURIComponent(list.join(",")));
    },
};
