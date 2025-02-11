var CACHE_NAME = 'gestione-spese-cache-v1';
var urlsToCache = [
  '/',
  '/static/style.css'
  // Aggiungi altri URL da cache, se necessario
];

self.addEventListener('install', function(event) {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(function(cache) {
        console.log('Aperto cache');
        return cache.addAll(urlsToCache);
      })
  );
});

self.addEventListener('fetch', function(event) {
  event.respondWith(
    caches.match(event.request)
      .then(function(response) {
        // Se esiste nella cache, restituisce la risposta
        if (response) {
          return response;
        }
        return fetch(event.request);
      })
  );
}); 