// api.js — thin fetch wrapper around the Stock Insights FastAPI backend.
//
// Token persistence: we stash the bearer token in localStorage. The server
// hands out 30-day tokens, so we don't need a refresh dance — if a call
// returns 401, we just bounce the user back to the login screen.
//
// Server URL: auto-detected from the page's origin. The PWA is normally
// served from the same FastAPI server it talks to, so window.location.origin
// is the right answer. To override (e.g. when hosting the PWA separately
// from the API), set window.SI_API_URL = "https://api.example.com" before
// app.js loads.
//
// Errors: every failed call rejects with an Error whose `.message` is safe to
// show in a toast and whose `.code` is the HTTP status, or 0 when the server
// could not be reached (offline, DNS, timeout).

const TOKEN_KEY = "si.token";
const USER_KEY = "si.user";

// Requests that take longer than this are aborted and reported as a timeout,
// so a dead tunnel doesn't leave the UI spinning until the browser gives up.
const TIMEOUT_MS = 15000;
// Idempotent GETs are retried once on a network error or a gateway error
// (Cloudflare returns 502/503/504 while the origin restarts).
const RETRY_STATUSES = new Set([502, 503, 504]);
const RETRY_DELAY_MS = 600;

// Clean up legacy localStorage entry from earlier versions that asked the
// user to type the server URL on the login screen.
try {
    localStorage.removeItem("si.server");
} catch (_) {
}

function _apiError(message, code) {
    const err = new Error(message);
    err.code = code;
    return err;
}

// FastAPI puts a string in `detail` for HTTPException, but a list of
// {loc, msg} objects for request-validation (422) errors.
function _detailMessage(detail) {
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail.length) {
        return detail.map(d => (d && d.msg) || String(d)).join("; ");
    }
    return "";
}

const _sleep = ms => new Promise(r => setTimeout(r, ms));

export const Api = {
    // ── Server URL (auto from origin; override via window.SI_API_URL) ─────
    getServer() {
        // window.SI_API_URL is an optional opt-in global; cast through `any`
        // so the JS lint doesn't flag it as undefined.
        const override = /** @type {any} */ (window).SI_API_URL;
        return (override || window.location.origin).replace(/\/+$/, "");
    },

    // ── Auth state ────────────────────────────────────────────────────────
    getToken() {
        return localStorage.getItem(TOKEN_KEY);
    },
    getUser() {
        const raw = localStorage.getItem(USER_KEY);
        if (!raw) return null;
        try {
            return JSON.parse(raw);
        } catch (_) {
            return null; // corrupted entry — treat as signed-out user info
        }
    },
    isAuthed() {
        return !!this.getToken();
    },
    clearAuth() {
        localStorage.removeItem(TOKEN_KEY);
        localStorage.removeItem(USER_KEY);
    },

    // ── Core request helper ───────────────────────────────────────────────
    /** opts: {method, body, headers, skipAuth, timeoutMs}. Resolves to the
     *  parsed JSON body (null for an empty body). */
    async _request(path, opts = {}) {
        const base = this.getServer();
        if (!base) throw _apiError("No server URL configured", 0);

        const method = opts.method || "GET";
        const headers = {...(opts.headers || {})};
        if (opts.body !== undefined) headers["Content-Type"] = "application/json";
        const token = this.getToken();
        if (token && !opts.skipAuth) headers["Authorization"] = `Bearer ${token}`;
        const body = opts.body !== undefined ? JSON.stringify(opts.body) : undefined;

        const attempts = method === "GET" ? 2 : 1;
        let res;
        for (let attempt = 1; ; attempt++) {
            if (navigator.onLine === false) {
                throw _apiError("You're offline — check your connection", 0);
            }
            const ctrl = new AbortController();
            const timer = setTimeout(() => ctrl.abort(), opts.timeoutMs || TIMEOUT_MS);
            try {
                res = await fetch(base + path, {
                    method, headers, body,
                    signal: ctrl.signal,
                    cache: "no-store", // portfolio data must never come from the HTTP cache
                });
            } catch (e) {
                res = null;
                if (attempt < attempts) {
                    await _sleep(RETRY_DELAY_MS);
                    continue;
                }
                throw _apiError(
                    e && e.name === "AbortError"
                        ? "The server took too long to respond"
                        : "Can't reach the server",
                    0,
                );
            } finally {
                clearTimeout(timer);
            }
            if (RETRY_STATUSES.has(res.status) && attempt < attempts) {
                await _sleep(RETRY_DELAY_MS);
                continue;
            }
            break;
        }

        if (res.status === 401 && !opts.skipAuth) {
            this.clearAuth();
            throw _apiError("Session expired", 401);
        }
        if (!res.ok) {
            let msg = `${res.status} ${res.statusText}`.trim();
            try {
                const data = await res.json();
                msg = _detailMessage(data && data.detail) || msg;
            } catch (_) {
                // non-JSON error page (e.g. a Cloudflare 52x) — keep status text
            }
            throw _apiError(msg, res.status);
        }
        if (res.status === 204) return null;
        const text = await res.text();
        return text ? JSON.parse(text) : null;
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
            // Short timeout: logging out must not hang when offline.
            await this._request("/auth/logout", {method: "POST", timeoutMs: 5000});
        } catch (_) {
            // Server-side revoke is best effort; the local token is dropped anyway.
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

    /** Live prices: resolves to {SYMBOL: price_or_null}. */
    async getQuotes(symbols) {
        const list = [...new Set(symbols.map(s => s.trim().toUpperCase()).filter(Boolean))];
        if (!list.length) return {};
        return this._request("/quotes?symbols=" + encodeURIComponent(list.join(",")));
    },
};
