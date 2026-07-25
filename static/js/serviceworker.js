const CACHE_NAME = 'school-sms-v2';
const urlsToCache = [
    '/',
    '/static/js/main.js',
    '/static/manifest.json',
    '/static/images/school_logo.png',
];

// Install — cache core assets
self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => cache.addAll(urlsToCache))
    );
    self.skipWaiting();
});

// Activate — clean old caches
self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(keys =>
            Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
        )
    );
    self.clients.claim();
});

// Fetch — network first, fallback to cache
self.addEventListener('fetch', event => {
    event.respondWith(
        fetch(event.request).catch(() => caches.match(event.request))
    );
});

// ── Push Notification Handler ──────────────────────────────────────────────
self.addEventListener('push', event => {
    let data = { title: 'New Notification', body: '', url: '/', icon: '/static/images/school_logo.png' };

    if (event.data) {
        try { data = { ...data, ...JSON.parse(event.data.text()) }; }
        catch (e) { data.body = event.data.text(); }
    }

    event.waitUntil(
        self.registration.showNotification(data.title, {
            body: data.body,
            icon: data.icon,
            badge: '/static/images/school_logo.png',
            data: { url: data.url },
            vibrate: [200, 100, 200],
        })
    );
});

// ── Notification Click — open the target URL ──────────────────────────────
self.addEventListener('notificationclick', event => {
    event.notification.close();
    const url = event.notification.data?.url || '/';
    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
            for (const client of list) {
                if (client.url === url && 'focus' in client) return client.focus();
            }
            return clients.openWindow(url);
        })
    );
});
