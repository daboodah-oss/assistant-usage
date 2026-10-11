// Assistant Usage dashboard service worker.
// Navigations: network-first with cached fallback (the page rebuilds often).
// Static icons/manifest: cache-first, they're immutable.
const PAGE_CACHE = 'ai-usage-page-v1';
const ASSET_CACHE = 'ai-usage-assets-v1';

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(ASSET_CACHE).then((cache) =>
      cache.addAll(['icons/icon-192.png', 'icons/icon-512.png'])
    ).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== PAGE_CACHE && k !== ASSET_CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request).then((res) => {
        const copy = res.clone();
        caches.open(PAGE_CACHE).then((c) => c.put(event.request, copy));
        return res;
      }).catch(() => caches.match(event.request))
    );
    return;
  }
  const url = new URL(event.request.url);
  if (url.pathname.includes('/icons/') || url.pathname.endsWith('.webmanifest')) {
    event.respondWith(
      caches.match(event.request).then((hit) => hit || fetch(event.request))
    );
  }
});
