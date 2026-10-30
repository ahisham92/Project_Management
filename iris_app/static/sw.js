// Iris service worker: shows a tool's notification and opens Iris on that tool.
// A notification says only who is asking; the message itself is read in the app.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = {}; }
  const scope = self.registration.scope;
  event.waitUntil(self.registration.showNotification(data.title || "Iris", {
    body: data.body || "You have a new message.",
    icon: scope + "static/icon-192.png",
    badge: scope + "static/badge-72.png",
    tag: data.tool ? "iris-tool-" + data.tool : "iris",
    renotify: true,
    data: { url: scope + (data.tool ? "?tool=" + data.tool : "") },
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data || {}).url || self.registration.scope;
  event.waitUntil((async () => {
    const open = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const client of open) {
      if (client.url.startsWith(self.registration.scope)) {
        await client.focus();
        return client.navigate(url);
      }
    }
    return self.clients.openWindow(url);
  })());
});
