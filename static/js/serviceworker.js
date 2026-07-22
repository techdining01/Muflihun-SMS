// javascript
// static/js/serviceworker.js
const CACHE_NAME = 'school-sms-v1';
const urlsToCache = [
    '/',
    '/static/js/main.js',
    '/static/manifest.json',
    '/static/images/school_logo.png',

    // Add paths to your icons here
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        console.log('Opened cache');
        return cache.addAll(urlsToCache);
      })
  );
});

self.addEventListener('fetch', event => {
  event.respondWith(
    caches.match(event.request)
      .then(response => {
        // Cache hit - return response
        if (response) {
          return response;
        }
        // No cache match - fetch from network
        return fetch(event.request);
      }
    )
  );
});