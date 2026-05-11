// sw.js — minimal service worker for installability + app-shell offline.
//
// Strategy:
//   - Pre-cache the static app shell on install (HTML, CSS, JS, icons).
//   - Network-first for API calls (anything to a different origin) so prices
//     are always fresh; we don't try to cache API responses.
//   - Cache-first for the shell so the PWA opens instantly from the home
//     screen, even on flaky reception.

// Bump this any time you change a file in the SHELL list below — the
// service-worker cache is keyed on VERSION, so without a bump phones
// keep serving the previous app.js / portfolio.js / styles.css from
// disk regardless of what the server hands out.
// v3 (May 2026): date-range filter + equity-curve card
const VERSION = "si-shell-v3";
const SHELL = [
  "./",
  "./index.html",
  "./styles.css",
  "./manifest.webmanifest",
  "./js/app.js",
  "./js/api.js",
  "./js/portfolio.js",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
];

self.addEventListener("install", e => {
  e.waitUntil(
      caches.open(VERSION)
          .then(c => c.addAll(SHELL))
          .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", e => {
  e.waitUntil(
      caches.keys().then(keys =>
          Promise.all(keys.filter(k => k !== VERSION).map(k => caches.delete(k)))
      ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  const sameOrigin = url.origin === self.location.origin;

  // API calls (cross-origin) — always go to network. No caching.
  if (!sameOrigin) return;

  // Same-origin: cache-first for shell, network fallback.
  e.respondWith(
      caches.match(e.request).then(hit => {
        if (hit) return hit;
        return fetch(e.request).then(res => {
          // Opportunistically cache successful responses.
          if (res.ok && (e.request.method === "GET")) {
            const copy = res.clone();
            caches.open(VERSION).then(c => c.put(e.request, copy));
          }
          return res;
        }).catch(() => caches.match("./index.html"));
      })
  );
});
