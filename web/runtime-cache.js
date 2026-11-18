/* Cache only versioned application assets. Forms and reports never enter this cache. */
const prefix = new URL(self.registration.scope).pathname;
const cacheName = "pharmadesk-runtime:" + prefix;

self.addEventListener("install", event => event.waitUntil(self.skipWaiting()));
self.addEventListener("activate", event => event.waitUntil(self.clients.claim()));

const versionedAsset = /^(?:runtime\/[0-9a-f]{16}\/[^/]+(?:\/[^/]+)?|python-[0-9a-f]{16}\.zip)$/;

self.addEventListener("fetch", event => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || request.headers.has("range") || url.origin !== self.location.origin ||
      !url.pathname.startsWith(prefix) || url.search) return;
  if (!versionedAsset.test(url.pathname.slice(prefix.length))) return;

  event.respondWith((async () => {
    const cache = await caches.open(cacheName).catch(() => null);
    const saved = await cache?.match(request).catch(() => null);
    if (saved) return saved;

    const response = await fetch(request);
    if (cache && response.status === 200 && !response.redirected) {
      event.waitUntil(cache.put(request, response.clone()).catch(() => {}));
    }
    return response;
  })());
});
