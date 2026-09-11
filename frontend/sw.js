const CACHE_NAME = 'legal-voice-v1';
const ASSETS = [
  '/',
  '/static/css/app.css',
  '/static/js/audio_engine.js',
  '/static/js/app.js',
  '/manifest.json'
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS))
  );
});

self.addEventListener('fetch', (e) => {
  if (e.request.url.includes('/api/') || e.request.url.includes('/ws/')) {
    return; // Pass through dynamic API/WebSocket requests
  }
  e.respondWith(
    caches.match(e.request).then((res) => res || fetch(e.request))
  );
});
