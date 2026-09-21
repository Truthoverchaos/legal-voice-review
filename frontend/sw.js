// Bump this on every deploy that touches a cached shell file, so old
// clients pick up the new version instead of being stuck on whatever
// they first installed. (Was a single hardcoded name with no way to
// ever invalidate it -- fixed 2026-09-20.)
const CACHE_NAME = 'legal-voice-v2';
const ASSETS = [
  '/',
  '/static/css/app.css',
  '/static/js/audio_engine.js',
  '/static/js/app.js',
  '/manifest.json'
];

self.addEventListener('install', (e) => {
  self.skipWaiting(); // Activate the new worker immediately, don't wait for old tabs to close.
  e.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS))
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((names) =>
      Promise.all(names.filter((n) => n !== CACHE_NAME).map((n) => caches.delete(n)))
    ).then(() => self.clients.claim()) // Take control of already-open tabs right away.
  );
});

self.addEventListener('fetch', (e) => {
  if (e.request.url.includes('/api/') || e.request.url.includes('/ws/')) {
    return; // Pass through dynamic API/WebSocket requests
  }

  // Network-first: always prefer the latest deployed version when online.
  // Only fall back to the cached copy if the network is unavailable
  // (offline use), and refresh the cache with whatever we get so the
  // offline fallback stays reasonably current too.
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(e.request, copy));
        return res;
      })
      .catch(() => caches.match(e.request))
  );
});
