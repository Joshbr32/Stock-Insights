// ui.js — DOM builders, number/date formatting and safe storage for the PWA.
//
// Everything here is pure presentation plumbing shared by app.js and
// charts.js. There is deliberately no innerHTML path: el() and svg() only
// ever create nodes and text nodes, so user data (symbols, notes, tags,
// account names) can never be parsed as markup.

const SVG_NS = "http://www.w3.org/2000/svg";

function applyAttrs(node, attrs) {
    for (const [k, v] of Object.entries(attrs)) {
        if (v === false || v == null) continue;
        if (k === "class") node.setAttribute("class", String(v));
        else if (k.startsWith("on") && typeof v === "function") {
            node.addEventListener(k.slice(2), v);
        } else node.setAttribute(k, String(v));
    }
}

function appendChildren(node, children) {
    for (const c of [].concat(children)) {
        if (c == null || c === false) continue;
        node.appendChild(typeof c === "object" ? c : document.createTextNode(String(c)));
    }
}

/** Create an HTML element. Strings in `children` become text nodes. */
export function el(tag, attrs = {}, children = []) {
    const node = document.createElement(tag);
    applyAttrs(node, attrs);
    appendChildren(node, children);
    return node;
}

/** Create an SVG element (namespaced, so it renders when appended). */
export function svg(tag, attrs = {}, children = []) {
    const node = document.createElementNS(SVG_NS, tag);
    applyAttrs(node, attrs);
    appendChildren(node, children);
    return node;
}

/** Small stroke icon on a 24-unit grid. `d` is one or more path strings. */
export function icon(d) {
    return svg("svg", {class: "icon", viewBox: "0 0 24 24", "aria-hidden": "true"},
        [].concat(d).map(p => svg("path", {d: p})));
}

export const ICONS = {
    home: ["M3 11l9-7 9 7", "M5 10v10h5v-6h4v6h5V10"],
    trades: ["M4 6h16", "M4 12h16", "M4 18h10"],
    goals: ["M12 3a9 9 0 1 0 9 9", "M12 7a5 5 0 1 0 5 5", "M12 12l8-8"],
    watch: ["M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z", "M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z"],
    settings: ["M4 7h10", "M18 7h2", "M4 17h4", "M12 17h8", "M16 5v4", "M10 15v4"],
    refresh: ["M20 11a8 8 0 1 0-2.3 5.7", "M20 4v7h-7"],
    close: ["M6 6l12 12", "M18 6L6 18"],
};

// ── Number formatting ─────────────────────────────────────────────────
// Negative numbers use a real minus sign (U+2212) so gains and losses
// read correctly without colour.
const MINUS = "−";
const usd = new Intl.NumberFormat("en-US", {
    style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2,
});
const usdWhole = new Intl.NumberFormat("en-US", {
    style: "currency", currency: "USD", maximumFractionDigits: 0,
});
const plain = new Intl.NumberFormat("en-US", {maximumFractionDigits: 2});

const DASH = "—";

/** $1,234.56 / −$88.00. `whole` drops cents (used on the pace rail). */
export function money(v, {whole = false} = {}) {
    if (v == null || Number.isNaN(v)) return DASH;
    const f = whole ? usdWhole : usd;
    return (v < 0 ? MINUS : "") + f.format(Math.abs(v));
}

/** Always signed: +$412.50 / −$88.00 / $0.00. */
export function signedMoney(v, opts) {
    if (v == null || Number.isNaN(v)) return DASH;
    if (Math.abs(v) < 0.005) return money(0, opts);
    return (v > 0 ? "+" : "") + money(v, opts);
}

/** Price/quantity without a currency symbol. */
export function num(v) {
    return v == null || Number.isNaN(v) ? DASH : plain.format(v);
}

export function percent(v, digits = 1) {
    return v == null || Number.isNaN(v) ? DASH : `${v.toFixed(digits)}%`;
}

/** ▲ 4.2% / ▼ 1.1% — the glyph carries direction for colour-blind users. */
export function pctChange(v, digits = 1) {
    if (v == null || Number.isNaN(v)) return DASH;
    if (Math.abs(v) < 0.05) return `${(0).toFixed(digits)}%`;
    return `${v > 0 ? "▲" : "▼"} ${Math.abs(v).toFixed(digits)}%`;
}

/** CSS tone class for a signed value. */
export function tone(v) {
    return v == null ? "" : v > 0.005 ? "good" : v < -0.005 ? "bad" : "";
}

// ── Dates ─────────────────────────────────────────────────────────────
const shortDate = new Intl.DateTimeFormat("en-US", {month: "short", day: "numeric"});
const longDate = new Intl.DateTimeFormat("en-US", {month: "short", day: "numeric", year: "numeric"});
const clock = new Intl.DateTimeFormat("en-US", {hour: "numeric", minute: "2-digit"});

/** "Mar 4" for a Date or epoch ms. */
export const fmtShortDate = d => shortDate.format(d);
export const fmtClock = d => clock.format(d);

/** "Mar 4, 2026" for a YYYY-MM-DD string; passes other strings through. */
export function fmtIsoDate(s) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s || "");
    if (!m) return s || DASH;
    return longDate.format(new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])));
}

export const plural = (n, one, many = one + "s") => `${n} ${n === 1 ? one : many}`;

// ── Storage ───────────────────────────────────────────────────────────
// localStorage throws in some private-browsing modes and when the quota
// is full; preferences are a convenience, so failures are ignored.
export const store = {
    get(key, fallback = null) {
        try {
            const v = localStorage.getItem(key);
            return v == null ? fallback : v;
        } catch {
            return fallback;
        }
    },
    set(key, value) {
        try {
            localStorage.setItem(key, value);
        } catch { /* preference not persisted; harmless */ }
    },
    remove(key) {
        try {
            localStorage.removeItem(key);
        } catch { /* ignore */ }
    },
};

export const reducedMotion = () =>
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
