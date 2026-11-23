// Network first for everything; the cache only helps offline or after a 4 s timeout.
// API calls, auth and health checks are never cached. Updates are silent.
import { version } from '$app/env';
import { assets, immutable } from '$app/manifest';
import { self as sw } from '$app/service-worker';

const CACHE = `finanzen-${version}`;
const abs = (p: string) => '/' + p.replace(/^\/+/, '');
const PRECACHE = [...immutable.map((f) => abs(f.path)), ...assets.map((f) => abs(f.path)), '/'];
const NEVER = ['/api/', '/auth/', '/healthz', '/oauth/', '/mcp', '/.well-known/', '/avatar/'];

sw.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(PRECACHE))
      .then(() => sw.skipWaiting())
  );
});

sw.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => sw.clients.claim())
  );
});

function timeout(ms: number): Promise<never> {
  return new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), ms));
}

const SHARE_CACHE = 'finanzen-share';
const SHARE_PATH = '/import/teilen';

// Web Share Target: a CSV shared to the app is parked in a cache and the import page picks it up.
async function receiveShare(req: Request): Promise<Response> {
  try {
    const form = await req.formData();
    const file = form.get('file');
    const cache = await caches.open(SHARE_CACHE);
    if (file instanceof File) {
      await cache.put(
        '/__shared/file',
        new Response(file, { headers: { 'Content-Type': file.type || 'text/csv', 'X-Filename': encodeURIComponent(file.name || 'geteilt.csv') } })
      );
      return Response.redirect('/import?geteilt=1', 303);
    }
    const text = String(form.get('text') ?? '');
    if (text.includes('\n')) {
      await cache.put('/__shared/file', new Response(text, { headers: { 'Content-Type': 'text/csv', 'X-Filename': 'geteilt.csv' } }));
      return Response.redirect('/import?geteilt=1', 303);
    }
  } catch {
    // fall through
  }
  return Response.redirect('/import?geteilt=fehler', 303);
}

sw.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method === 'POST' && new URL(req.url).pathname === SHARE_PATH) {
    event.respondWith(receiveShare(req));
    return;
  }
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== sw.location.origin) return;
  if (NEVER.some((p) => url.pathname.startsWith(p))) return;

  event.respondWith(
    (async () => {
      const cache = await caches.open(CACHE);
      try {
        const res = await Promise.race([fetch(req), timeout(4000)]);
        if (res.ok && res.type === 'basic') cache.put(req, res.clone());
        return res;
      } catch {
        const cached = await cache.match(req);
        if (cached) return cached;
        if (req.mode === 'navigate') {
          const shell = await cache.match('/');
          if (shell) return shell;
        }
        return new Response('Offline', { status: 503, statusText: 'Offline' });
      }
    })()
  );
});

// Web push: show the notification; a click opens (or focuses) the app at the given page.
sw.addEventListener('push', (event) => {
  let data: { title?: string; body?: string; url?: string } = {};
  try {
    data = event.data?.json() ?? {};
  } catch {
    data = { body: event.data?.text() };
  }
  event.waitUntil(
    sw.registration.showNotification(data.title || 'Finanzen', {
      body: data.body || '',
      icon: '/icon-192.png',
      badge: '/icon-192.png',
      data: { url: data.url || '/' },
      tag: data.title
    })
  );
});

sw.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = new URL((event.notification.data as { url?: string })?.url || '/', sw.location.origin).href;
  event.waitUntil(
    (async () => {
      const windows = await sw.clients.matchAll({ type: 'window', includeUncontrolled: true });
      for (const client of windows) {
        if (new URL(client.url).origin === sw.location.origin && 'focus' in client) {
          await client.focus();
          if ('navigate' in client) await (client as WindowClient).navigate(url);
          return;
        }
      }
      await sw.clients.openWindow(url);
    })()
  );
});
