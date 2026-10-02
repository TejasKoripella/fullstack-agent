// Network only: the service worker never caches conversations or media.
self.addEventListener("fetch", event => {
  event.respondWith(fetch(event.request));
});
