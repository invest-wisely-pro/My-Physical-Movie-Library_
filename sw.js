/* My Physical Movie Library — service worker (versione pubblicata su un sito).
   - L'app (index.html): prima la rete, così gli aggiornamenti arrivano subito;
     senza rete, l'ultima copia salvata → funziona anche offline.
   - Librerie (cdnjs), font e icone: prima la copia salvata, poi la rete.
   - Locandine: copia salvata (massimo 400, le più vecchie si eliminano).
   - Wikidata / Wikipedia / proxy: sempre rete (i dati li gestisce l'app). */
const VERSION = 'mpml-2026-10-20';
const SHELL = VERSION + '-shell', IMG = 'mpml-locandine';
const SHELL_FILES = ['./', './index.html', './manifest.webmanifest', './icons/icon-192.png', './icons/icon-512.png', './icons/apple-touch-icon.png'];
const IMG_MAX = 400;

self.addEventListener('install', e => {
  e.waitUntil(caches.open(SHELL).then(c => c.addAll(SHELL_FILES)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k !== SHELL && k !== IMG).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
async function trimImages(){
  const c = await caches.open(IMG); const keys = await c.keys();
  for(let i = 0; i < keys.length - IMG_MAX; i++) await c.delete(keys[i]);
}
self.addEventListener('fetch', e => {
  const req = e.request;
  if(req.method !== 'GET') return;
  const url = new URL(req.url);
  if(/(^|\.)wikidata\.org$|(^|\.)wikipedia\.org$|allorigins|codetabs|corsproxy|youtube|ytimg/.test(url.hostname)) return;
  // L'app: rete prima, copia salvata se offline
  if(req.mode === 'navigate' || (url.origin === self.location.origin && /\/(index\.html)?$/.test(url.pathname))){
    e.respondWith(fetch(req).then(res => {
      if(res && res.ok){ const copy = res.clone(); caches.open(SHELL).then(c => c.put('./index.html', copy)); }
      return res;
    }).catch(() => caches.match('./index.html').then(r => r || caches.match('./'))));
    return;
  }
  // Locandine (Wikimedia, IMDb/Amazon): copia salvata prima
  if(req.destination === 'image' && /upload\.wikimedia\.org|commons\.wikimedia\.org|media-amazon\.com/.test(url.hostname)){
    e.respondWith(caches.open(IMG).then(c => c.match(req).then(hit => hit || fetch(req).then(res => {
      if(res && (res.ok || res.type === 'opaque')){ c.put(req, res.clone()); trimImages(); }
      return res;
    }))));
    return;
  }
  // File del sito, librerie e font: copia salvata prima, poi rete
  if(url.origin === self.location.origin || /cdnjs\.cloudflare\.com|fonts\.googleapis\.com|fonts\.gstatic\.com/.test(url.hostname)){
    e.respondWith(caches.match(req).then(hit => hit || fetch(req).then(res => {
      if(res && (res.ok || res.type === 'opaque')){ const copy = res.clone(); caches.open(SHELL).then(c => c.put(req, copy)); }
      return res;
    })));
  }
});
