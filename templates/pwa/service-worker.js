{% load static %}/* Zynora service worker. Precaches the static shell (css/js/icons) for
 * installability and a working offline page; never caches navigations or API
 * responses, since those can carry another person's photos or messages. */
const OFFLINE_URL = "{% url 'common:offline' %}";
const CACHE_NAME = "zynora-static::{% static 'css/zynora.css' %}::{% static 'js/zynora.js' %}";

const PRECACHE_URLS = [
    "{% static 'css/zynora.css' %}",
    "{% static 'js/zynora.js' %}",
    "{% static 'js/chat.js' %}",
    "{% static 'js/charts.js' %}",
    "{% static 'img/favicon.svg' %}",
    "{% static 'img/icons/icon-192.png' %}",
    "{% static 'img/icons/icon-512.png' %}",
    OFFLINE_URL,
];

self.addEventListener("install", (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then((cache) => cache.addAll(PRECACHE_URLS))
            .then(() => self.skipWaiting())
    );
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys()
            .then((names) => Promise.all(
                names.filter((name) => name !== CACHE_NAME).map((name) => caches.delete(name))
            ))
            .then(() => self.clients.claim())
    );
});

self.addEventListener("fetch", (event) => {
    const { request } = event;
    if (request.method !== "GET") return;

    const url = new URL(request.url);

    if (url.origin === self.location.origin && url.pathname.startsWith("/static/")) {
        event.respondWith(
            caches.match(request).then((cached) => cached || fetch(request).then((response) => {
                const copy = response.clone();
                caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
                return response;
            }))
        );
        return;
    }

    if (request.mode === "navigate") {
        event.respondWith(fetch(request).catch(() => caches.match(OFFLINE_URL)));
    }
});
