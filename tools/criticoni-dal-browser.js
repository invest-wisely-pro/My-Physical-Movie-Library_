/*
  Frusciante e i Criticoni: aggiornamento a mano, dal tuo browser.

  Serve quando filmcriticoni.it blocca gli accessi automatici dei server (come da novembre 2026).
  1. Sul computer apri https://filmcriticoni.it/ con Chrome, Edge o Firefox.
  2. Premi F12 → scheda "Console". (La prima volta Chrome chiede di scrivere  allow pasting  e premere Invio.)
  3. Incolla tutto questo file e premi Invio. In alto a destra compare un riquadro con l'avanzamento:
     legge gli elenchi con calma, una pagina al secondo, come se li sfogliassi tu (circa 5-10 minuti).
  4. Alla fine scarica il file  criticoni-pagine.json.gz : su GitHub caricalo nella cartella  data/  del repository
     (Add file → Upload files), sostituendo quello vecchio se c'è.
  L'aggiornamento notturno lo usa da solo quando il sito non risponde. Nessuna chiave, nessun dato personale:
  il file contiene solo le pagine degli elenchi dei film.
*/
(async () => {
  const PAUSA = 1000, MAX = 400, sleep = ms => new Promise(r => setTimeout(r, ms));
  if (!/filmcriticoni\.it$/.test(location.hostname)) { alert('Apri prima https://filmcriticoni.it/ e incolla lo script nella console di quella pagina.'); return; }
  const box = document.createElement('div');
  box.style.cssText = 'position:fixed;top:12px;right:12px;z-index:2147483647;background:#111;color:#fff;font:14px/1.4 system-ui,sans-serif;padding:12px 16px;border-radius:10px;box-shadow:0 6px 24px rgba(0,0,0,.5);max-width:340px';
  document.body.appendChild(box);
  const say = t => { box.textContent = t; };
  const out = { v: 1, saved: new Date().toISOString().slice(0, 10), site: location.origin, pages: {} };
  const filmRe = { c: /(?:["'\s=]|filmcriticoni\.it)\/film\/([a-z0-9][a-z0-9-]*)/g, f: /\/frusciante\/film\/([a-z0-9][a-z0-9-]*)/g };
  const get = async url => {
    for (let k = 0; k < 4; k++) {
      const r = await fetch(url, { credentials: 'same-origin' });
      if (r.ok) return r.text();
      if (r.status === 429 || r.status >= 500) { say(`Il sito chiede di rallentare: aspetto ${10 * (k + 1)} secondi…`); await sleep(10000 * (k + 1)); continue; }
      throw new Error(`${url}: risposta ${r.status}`);
    }
    throw new Error(`${url}: il sito non risponde`);
  };
  try {
    for (const [src, path, name] of [['c', '/', 'Criticoni'], ['f', '/frusciante', 'Frusciante']]) {
      let page = 1, last = 1, empty = 0; const seen = new Set();
      while (page <= Math.min(last, MAX)) {
        const t = await get(path + (page === 1 ? '' : '?page=' + page));
        out.pages[`${src}-${page}.html`] = t;
        for (const m of t.matchAll(/[?&](?:amp;)?page=(\d+)/g)) last = Math.max(last, +m[1]);
        let n = 0; for (const m of t.matchAll(filmRe[src])) if (!seen.has(m[1])) { seen.add(m[1]); n++; }
        empty = n ? 0 : empty + 1;
        say(`${name}: pagina ${page} di ${last} · ${seen.size} film`);
        if (empty >= 2) break;
        page++; await sleep(PAUSA);
      }
      if (seen.size < (src === 'c' ? 300 : 1000)) throw new Error(`${name}: trovati solo ${seen.size} film, la struttura del sito potrebbe essere cambiata`);
    }
    say('Preparo il file…');
    const json = new Blob([JSON.stringify(out)], { type: 'application/json' });
    const gz = await new Response(json.stream().pipeThrough(new CompressionStream('gzip'))).blob();
    const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(gz), download: 'criticoni-pagine.json.gz' });
    document.body.appendChild(a); a.click(); a.remove();
    say(`✅ Fatto: ${Object.keys(out.pages).length} pagine salvate in criticoni-pagine.json.gz (${Math.round(gz.size / 1024)} KB). Caricalo su GitHub nella cartella data/.`);
  } catch (e) {
    say('❌ ' + e.message); console.error(e);
  }
})();
