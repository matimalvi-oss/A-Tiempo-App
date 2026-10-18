// sw.js - Service Worker para PWA
const CACHE_NAME = 'delivery-app-v2';
const urlsToCache = [
  '/',
  '/index.html',
  '/manifest.json',
  '/static/style.css',
  '/static/app.js',
  '/icon-192.png',
  '/icon-512.png'
];

// Instalación: guarda en caché los archivos principales
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(urlsToCache))
  );
});

// Activación: limpia cachés viejas
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.map(cacheName => {
          if (cacheName !== CACHE_NAME) {
            return caches.delete(cacheName);
          }
        })
      );
    })
  );
});

// Fetch: sirve desde caché, si falla va a la red
self.addEventListener('fetch', event => {
  event.respondWith(
    caches.match(event.request)
      .then(response => {
        // Si está en caché, lo devuelve
        if (response) {
          return response;
        }
        // Si no, lo busca en la red
        return fetch(event.request).then(response => {
          // Si es una respuesta válida, la guarda en caché
          if (!response || response.status !== 200 || response.type !== 'basic') {
            return response;
          }
          const responseToCache = response.clone();
          caches.open(CACHE_NAME).then(cache => {
            cache.put(event.request, responseToCache);
          });
          return response;
        });
      })
  );
});