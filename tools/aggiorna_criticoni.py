#!/usr/bin/env python3
"""
Indice "Frusciante e i Criticoni" per My Physical Movie Library.

Legge, una volta al mese, SOLO gli elenchi dei film di filmcriticoni.it (indice indipendente dei
film discussi nei video di Federico Frusciante e dei Criticoni) e scrive nell'app un indice compatto:
per ogni film titolo, anno, regista, giudizio complessivo, numero di video e di menzioni, indirizzo
della sua pagina e la locandina (un'immagine di TMDB, che il sito usa).
Le locandine stanno negli elenchi (nelle schede o nei dati che il browser usa per disegnarle); nelle pagine dei
film si prendono solo immagini in formato locandina, mai lo sfondo panoramico del riquadro video (w780 e oltre).
Le pagine dei film si leggono una volta sola: i mesi dopo solo quelle dei film nuovi. Le frasi trascritte delle menzioni NON vengono copiate: per quelle l'app rimanda
alla pagina del film sul sito.

Uso:
  python tools/aggiorna_criticoni.py index.html                 # dal sito (una pagina al secondo)
  python tools/aggiorna_criticoni.py index.html --local CARTELLA # da pagine salvate (c-1.html, f-1.html, …)

Copia di sicurezza: l'indice viene salvato anche in data/criticoni.json.gz, accanto a index.html.
Se il sito non risponde o cambia struttura (troppo pochi film), lo script rimette nell'app l'ultima
copia salvata invece di fermarsi: i giudizi raccolti non si perdono, anche caricando un index.html nuovo.
Solo se manca anche la copia si ferma con un errore, SENZA modificare index.html.
"""
import base64, datetime, gzip, html, json, os, re, sys, time, urllib.parse, urllib.request
from html.parser import HTMLParser

BASE = 'https://filmcriticoni.it'
SOURCES = {'c': '/', 'f': '/frusciante'}           # c = Criticoni, f = Frusciante
UA = 'MyPhysicalMovieLibrary-index/1.0 (indice personale aggiornato una volta al mese)'
SENT = {'positivo': 1, 'negativo': -1, 'misto': 0}
MIN_FILMS = {'c': 300, 'f': 1000}                   # sotto queste soglie qualcosa non va
HREF_RE = re.compile(r'^(?:https?://(?:www\.)?filmcriticoni\.it)?/(frusciante/)?film/([a-z0-9][a-z0-9-]*)/?$')
PAGE_RE = re.compile(r'[?&]page=(\d+)')
POSTER_RE = re.compile(r'image\.tmdb\.org/t/p/(?:w92|w154|w185|w300|w342|w500)(/[A-Za-z0-9_\-]+\.(?:jpg|jpeg|png|webp))', re.I)   # misure da locandina, mai gli sfondi
KEY_RE = re.compile(r'"[A-Za-z_]*[pP]oster[A-Za-z_]*"\s*:\s*"(?:https?://image\.tmdb\.org/t/p/[a-z0-9]+)?(/[A-Za-z0-9_\-]+\.(?:jpg|jpeg|png|webp))"')
POSTER_V = 2   # versione delle locandine: quelle raccolte prima (sfondi) si ignorano


def plain(page):
    """La pagina con i dati incorporati resi leggibili: niente codifiche %2F né virgolette precedute da \\."""
    t = urllib.parse.unquote(page)
    for _ in range(3): t = t.replace('\\"', '"')
    return t


def json_posters(page, slugs):
    """Locandine nei dati incorporati degli elenchi: per ogni film, la voce "poster…" dentro la sua stessa voce."""
    t, out = plain(page), {}
    for slug in slugs:
        for m in re.finditer(r'film/' + re.escape(slug) + r'(?![A-Za-z0-9\-])', t):
            a, b = t.rfind('{', 0, m.start()), t.find('}', m.end())   # solo dentro la voce di questo film, mai quella accanto
            if a < 0 or b < 0 or m.start() - a > 2000 or b - m.end() > 2000: continue
            win = t[a:b]
            k = KEY_RE.search(win) or POSTER_RE.search(win)
            if k: out[slug] = k.group(1); break
    return out


class ListParser(HTMLParser):
    """Raccoglie, per ogni link a una scheda film, i pezzi di testo che contiene."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cards, self.pages, self._cur, self._depth = [], set(), None, 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'a':
            href = (a.get('href') or '').strip()
            m = HREF_RE.match(href)
            if m and self._cur is None:
                self._cur = {'fr': bool(m.group(1)), 'slug': m.group(2), 'chunks': [], 'alt': '', 'img': ''}
                self._depth = 1
                return
            pm = PAGE_RE.search(href)
            if pm: self.pages.add(int(pm.group(1)))
        if self._cur is not None:
            if tag == 'a': self._depth += 1
            if tag == 'img' and a.get('alt') and not self._cur['alt']: self._cur['alt'] = a['alt'].strip()
            if tag in ('img', 'source') and not self._cur['img']:
                for k in ('src', 'srcset', 'data-src'):   # anche quando passa per l'ottimizzatore di immagini (/_next/image?url=…)
                    pm = POSTER_RE.search(urllib.parse.unquote(a.get(k) or ''))
                    if pm: self._cur['img'] = pm.group(1); break

    def handle_endtag(self, tag):
        if self._cur is not None and tag == 'a':
            self._depth -= 1
            if self._depth <= 0:
                self.cards.append(self._cur); self._cur = None

    def handle_data(self, data):
        if self._cur is not None:
            t = re.sub(r'\s+', ' ', data).strip()
            if t: self._cur['chunks'].append(t)


def parse_card(c):
    ch = [x for x in c['chunks'] if x not in ('→', '›')]
    joined = ' '.join(ch)
    m = re.search(r'(\d+)\s*video\s*·\s*(\d+)\s*menzion', joined)
    if not m: return None
    vid, men = int(m.group(1)), int(m.group(2))
    sent = None
    for x in ch:
        if x.lower() in SENT: sent = SENT[x.lower()]; break
    year = ''
    for x in ch:
        ym = re.match(r'^((?:18|19|20)\d{2})(?!\d)', x)
        if ym: year = ym.group(1); break
    director, title = '', ''
    ri = next((i for i, x in enumerate(ch) if x.lower().startswith('regia')), -1)
    if ri >= 0:
        d = re.sub(r'^regia\s*:?\s*', '', ch[ri], flags=re.I).strip()
        if not d and ri + 1 < len(ch): d = ch[ri + 1]
        director = d
        for j in range(ri - 1, -1, -1):              # il titolo è il testo subito prima di "Regia"
            x = ch[j]
            if x.lower() in SENT or re.match(r'^((?:18|19|20)\d{2})', x) or re.match(r'^uwufufu', x, re.I) or x.startswith('#'): continue
            title = x; break
    if not title: title = c['alt']
    if not title:                                    # ultimo ripiego: il testo prima del giudizio o dell'anno
        tm = re.match(r'^(.*?)\s+(?:Positivo|Negativo|Misto|(?:18|19|20)\d{2})\b', joined)
        title = tm.group(1).strip() if tm else ''
    if not title: return None
    return [c['slug'], html.unescape(title), year, html.unescape(director), sent, vid, men, c.get('img', '')]


def get(url, tries=4):
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'text/html'})
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode('utf-8', 'replace')
        except Exception as e:
            if k == tries - 1: raise
            print(f'  nuovo tentativo tra {5 * (k + 1)} s ({e})'); time.sleep(5 * (k + 1))


def crawl(src, local=None, delay=1.0, max_pages=400):
    films, seen, page, last, empty = [], set(), 1, 1, 0
    while page <= min(last, max_pages):
        if local:
            path = os.path.join(local, f'{src}-{page}.html')
            if not os.path.exists(path): break
            text = open(path, encoding='utf-8').read()
        else:
            url = BASE + SOURCES[src] + ('' if page == 1 else ('&' if '?' in SOURCES[src] else '?') + f'page={page}')
            text = get(url)
            time.sleep(delay)
        p = ListParser(); p.feed(text)
        if p.pages: last = max(last, max(p.pages))
        n, new = 0, []
        for c in p.cards:
            if (src == 'f') != c['fr']: continue        # solo le schede della sezione giusta
            row = parse_card(c)
            if row and row[0] not in seen:
                seen.add(row[0]); films.append(row); new.append(row); n += 1
        missing = [r[0] for r in new if not r[7]]
        if missing:                                     # locandine nei dati incorporati della pagina
            found = json_posters(text, missing)
            for r in new:
                if not r[7] and found.get(r[0]): r[7] = found[r[0]]
        print(f'  {"Criticoni" if src == "c" else "Frusciante"} pagina {page}/{last}: {n} film')
        empty = empty + 1 if n == 0 else 0
        if empty >= 2: break
        page += 1
    return films


FILM_PATH = {'c': '/film/', 'f': '/frusciante/film/'}
NO_POSTER = '!'   # pagina letta, ma senza immagine: non si rilegge


def film_poster(src, slug, local=None):
    """La locandina dalla pagina del film: negli elenchi del sito le immagini le aggiunge il browser, qui ci sono."""
    if local:
        path = os.path.join(local, f'film-{src}-{slug}.html')
        if not os.path.exists(path): return NO_POSTER
        page = open(path, encoding='utf-8').read()
    else:
        page = get(BASE + FILM_PATH[src] + urllib.parse.quote(slug))
    t = plain(page)
    m = KEY_RE.search(t) or POSTER_RE.search(t)   # una voce "poster…", oppure un'immagine in formato locandina
    return m.group(1) if m else NO_POSTER


def fill_posters(data, prev, local=None, delay=1.0, budget_s=300 * 60):
    """Completa le locandine: prima dalla copia del mese prima, poi leggendo le pagine dei film mancanti,
    dai più discussi. Restituisce (pagine lette, film rimasti per il mese prossimo)."""
    known = {(src, r[0]): r[7] for src in ('c', 'f') for r in prev.get(src, []) if len(r) > 7 and r[7]} if prev.get('pv') == POSTER_V else {}   # le vecchie (sfondi) no
    same = {}                                                    # stesso film in entrambi gli elenchi: una pagina sola
    rows = [(src, r) for src in ('c', 'f') for r in data[src]]
    for src, r in rows:
        if not r[7] and known.get((src, r[0])): r[7] = known[(src, r[0])]
        if r[7] and r[7] != NO_POSTER: same[(r[0], r[2])] = r[7]
    todo = sorted([x for x in rows if not x[1][7]], key=lambda x: -(x[1][6] or 0))
    t0, read, left = time.time(), 0, 0
    for src, r in todo:
        if same.get((r[0], r[2])): r[7] = same[(r[0], r[2])]; continue
        if time.time() - t0 > budget_s: left += 1; continue
        try: r[7] = film_poster(src, r[0], local); read += 1
        except Exception: r[7] = ''                              # si riprova il mese prossimo
        if r[7] and r[7] != NO_POSTER: same[(r[0], r[2])] = r[7]
        if not local: time.sleep(delay)
        if read and read % 500 == 0: print(f'  {read} pagine dei film lette…')
    return read, left


def embed(html_path, data, built):
    b64 = base64.b64encode(gzip.compress(json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf-8'), 9)).decode('ascii')
    tag = f'<script type="text/plain" id="criticoniData" data-built="{built}">{b64}</script>'
    doc = open(html_path, encoding='utf-8').read()
    new, n = re.subn(r'<script type="text/plain" id="criticoniData"[^>]*>[^<]*</script>', lambda _: tag, doc, count=1)
    if n == 0:
        new, n = re.subn(r'(<script type="text/plain" id="imdbSeriesData"[^>]*>[^<]*</script>)', lambda m: m.group(1) + '\n' + tag, doc, count=1)
    if n == 0:
        new = doc.replace('</body>', tag + '\n</body>', 1)
    open(html_path, 'w', encoding='utf-8').write(new)
    return len(b64)


def backup_path(html_path):
    return os.path.join(os.path.dirname(os.path.abspath(html_path)), 'data', 'criticoni.json.gz')


def save_backup(html_path, data):
    bp = backup_path(html_path); os.makedirs(os.path.dirname(bp), exist_ok=True)
    with open(bp, 'wb') as f: f.write(gzip.compress(json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf-8'), 9))


def restore_backup(html_path, reason):
    bp = backup_path(html_path)
    if not os.path.exists(bp):
        print(f'ERRORE: {reason} e non c\'è una copia salvata (data/criticoni.json.gz): index.html NON è stato modificato.')
        sys.exit(1)
    data = json.loads(gzip.decompress(open(bp, 'rb').read()).decode('utf-8'))
    embed(html_path, data, data.get('built', ''))
    print(f'ATTENZIONE: {reason}. Rimessa nell\'app l\'ultima copia salvata (del {data.get("built", "?")}): '
          f'{len(data.get("c", []))} film dei Criticoni e {len(data.get("f", []))} di Frusciante.')
    sys.exit(0)


def main():
    args = sys.argv[1:]
    if not args: print(__doc__); sys.exit(2)
    html_path = args[0]
    local = args[args.index('--local') + 1] if '--local' in args else None
    built = args[args.index('--date') + 1] if '--date' in args else datetime.date.today().isoformat()
    mins = {'c': 1, 'f': 1} if '--no-min' in args else MIN_FILMS
    data = {'v': 1, 'pv': POSTER_V, 'built': built, 'site': BASE}
    for src in ('c', 'f'):
        print(f'Leggo gli elenchi: {"Criticoni" if src == "c" else "Frusciante"}…')
        try:
            data[src] = crawl(src, local=local, delay=0 if local else 1.0)
        except Exception as e:
            restore_backup(html_path, f'il sito non risponde ({e})')
        if len(data[src]) < mins[src]:
            restore_backup(html_path, f'trovati solo {len(data[src])} film per {"i Criticoni" if src == "c" else "Frusciante"} '
                                      f'(attesi almeno {mins[src]}): la struttura del sito potrebbe essere cambiata')
    prev = {}
    try: prev = json.loads(gzip.decompress(open(backup_path(html_path), 'rb').read()).decode('utf-8'))
    except Exception: pass
    budget = float(args[args.index('--max-minutes') + 1]) if '--max-minutes' in args else 300.0
    print('Leggo le locandine dalle pagine dei film (solo quelle nuove)…')
    read, left = fill_posters(data, prev, local=local, delay=0 if local else 1.0, budget_s=budget * 60)
    print(f'Pagine dei film lette questo mese: {read}.' + (f' Ne restano {left}: si riprende il mese prossimo.' if left else ''))
    size = embed(html_path, data, built)
    save_backup(html_path, data)
    np = len({r[7] for src in ('c', 'f') for r in data[src] if len(r) > 7 and r[7] and r[7] != NO_POSTER})
    print(f'Fatto: {len(data["c"])} film dei Criticoni e {len(data["f"])} di Frusciante, {np} locandine, indice di {size // 1024} KB, data {built}.')


if __name__ == '__main__':
    main()
