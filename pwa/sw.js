// sw.js — minimal service worker for installability + app-shell offline.
//
// Strategy:
//   - Pre-cache the static app shell on install (HTML, CSS, JS, icons),
//     bypassing the HTTP cache so a new VERSION really gets new files.
//   - Cache-first for static shell assets so the PWA opens instantly from the
//     home screen, even on flaky reception.
//   - API calls are never touched: the API is served from the same origin as
//     the PWA, so anything that is not a static asset or a page navigation
//     (and anything carrying an Authorization header) goes straight to the
//     network. Caching /trades or /quotes here would show stale portfolio
//     data until the next VERSION bump.
//   - Offline page navigations fall back to the cached index.html.

// Bump this any time you change a file in the SHELL list below — the
// service-worker cache is keyed on VERSION, so without a bump phones
// keep serving the previous app.js / portfolio.js / styles.css from
// disk regardless of what the server hands out.
// v3 (May 2026): date-range filter + equity-curve card
// v4 (May 2026): drawdown metrics, hover/tap tooltip, daily resampling,
//                trade tags, mobile backup/restore
// v5 (May 2026): per-symbol drill-down modal (mini equity curve +
//                chronological trade list inside holding detail)
const VERSION = "si-shell-v7";
const CACHE_PREFIX = "si-shell-";
const SHELL = [
  "./",
  "./index.html",
  "./styles.css",
  "./manifest.webmanifest",
  "./js/app.js",
  "./js/api.js",
  "./js/portfolio.js",
  "./js/ui.js",
  "./js/charts.js",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
];

// Only these file types are ever served from / written to the cache.
const STATIC_EXT = /\.(?:html|css|js|png|svg|ico|webmanifest|woff2?)$/i;

self.addEventListener("install", e => {
  e.waitUntil(
      caches.open(VERSION)
          .then(c => c.addAll(SHELL.map(u => new Request(u, {cache: "reload"}))))
          .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", e => {
  e.waitUntil(
      caches.keys().then(keys =>
          Promise.all(keys
              .filter(k => k.startsWith(CACHE_PREFIX) && k !== VERSION)
              .map(k => caches.delete(k)))
      ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  // Cross-origin (incl. a separately hosted API via SI_API_URL): network only.
  if (url.origin !== self.location.origin) return;
  // Authenticated calls are API calls: network only, never cached.
  if (req.headers.has("Authorization")) return;

  if (req.mode === "navigate") {
    // Page loads: cached shell first (query strings ignored), then network,
    // then index.html when offline.
    e.respondWith(
        caches.match(req, {ignoreSearch: true})
            .then(hit => hit || fetch(req))
            .catch(() => caches.match("./index.html"))
    );
    return;
  }

  // Anything that isn't a static asset (e.g. /health, /quotes, /docs) is API.
  if (!STATIC_EXT.test(url.pathname)) return;

  e.respondWith(
      caches.match(req).then(hit => {
        if (hit) return hit;
        return fetch(req).then(res => {
          // Opportunistically cache static assets that weren't pre-cached
          // (e.g. the maskable icon the OS fetches on install).
          if (res.ok) {
            const copy = res.clone();
            caches.open(VERSION).then(c => c.put(req, copy));
          }
          return res;
        });
      })
  );
});
