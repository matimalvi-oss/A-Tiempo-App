// sw.js - Service Worker para PWA
const CACHE_NAME = 'delivery-app-v5';
const urlsToCache = [
  '/',
  '/manifest.json',
  '/static/style.css',
  '/static/app.js',
  '/static/icon-192.png',
  '/static/icon-512.png'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(urlsToCache))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(cacheNames => Promise.all(
      cacheNames.map(cacheName => cacheName !== CACHE_NAME && caches.delete(cacheName))
    )).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  const requestUrl = new URL(event.request.url);
  if (requestUrl.origin !== self.location.origin || requestUrl.pathname.startsWith('/api/')) {
    return;
  }

  event.respondWith(
    fetch(new Request(event.request, { cache: 'no-cache' }))
      .then(response => {
        if (response.ok && response.type === 'basic') {
          const responseToCache = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, responseToCache));
        }
        return response;
      })
      .catch(async () => {
        const cachedResponse = await caches.match(event.request);
        return cachedResponse || Response.error();
      })
  );
});
