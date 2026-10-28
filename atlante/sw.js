/* Atlante del Cinema — service worker (solo la cartella atlante/).
   - L'app: prima la rete, copia salvata se offline.
   - Gli indici della Videoteca (../index.html, ../data/*.gz): copia salvata subito, aggiornata in sottofondo.
   - Locandine: copia salvata (massimo 300). Wikidata, Wikipedia, YouTube: sempre rete. */
const VERSION = 'atlante-1.3';
const SHELL = VERSION + '-shell', DATA = 'atlante-dati', IMG = 'atlante-locandine';
const SHELL_FILES = ['./', './index.html', './manifest.webmanifest', './icons/icon-192.png', './icons/icon-512.png', './icons/apple-touch-icon.png', './fonts/inter-var.woff2'];
self.addEventListener('install', e => { e.waitUntil(caches.open(SHELL).then(c => c.addAll(SHELL_FILES)).then(() => self.skipWaiting())); });
self.addEventListener('activate', e => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== SHELL && k !== DATA && k !== IMG).map(k => caches.delete(k)))).then(() => self.clients.claim())); });
self.addEventListener('fetch', e => {
  const req = e.request; if(req.method !== 'GET') return;
  const url = new URL(req.url);
  if(/(^|\.)wikidata\.org$|(^|\.)wikipedia\.org$|youtube|filmcriticoni|api\.tvmaze\.com/.test(url.hostname)) return;
  if(url.origin === self.location.origin){
    const inApp = url.pathname.includes('/atlante/');
    if(inApp && (req.mode === 'navigate' || /\/atlante\/(index\.html)?$/.test(url.pathname))){
      e.respondWith(fetch(req).then(r => { if(r && r.ok){ const c = r.clone(); caches.open(SHELL).then(x => x.put('./index.html', c)); } return r; }).catch(() => caches.match('./index.html')));
      return;
    }
    if(!inApp && (/\/index\.html$/.test(url.pathname) || /\/data\/[^/]+\.gz$/.test(url.pathname))){   // indici: subito la copia, aggiornata dietro le quinte
      const key = new Request(url.origin + url.pathname);
      e.respondWith(caches.open(DATA).then(async c => { const hit = await c.match(key);
        const net = fetch(req).then(r => { if(r && r.ok) c.put(key, r.clone()); return r; }).catch(() => hit);
        return hit ? (e.waitUntil(net), hit) : net; }));
      return;
    }
    e.respondWith(caches.match(req).then(hit => hit || fetch(req)));
    return;
  }
  if(req.destination === 'image' && /upload\.wikimedia\.org|image\.tmdb\.org|static\.tvmaze\.com/.test(url.hostname)){
    e.respondWith(caches.open(IMG).then(c => c.match(req).then(hit => hit || fetch(req).then(async r => { if(r && (r.ok || r.type === 'opaque')){ c.put(req, r.clone()); const ks = await c.keys(); for(let i = 0; i < ks.length - 800; i++) c.delete(ks[i]); } return r; }))));
  }
});
