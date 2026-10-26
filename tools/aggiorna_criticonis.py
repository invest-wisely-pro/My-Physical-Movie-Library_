#!/usr/bin/env python3
"""
Indice "Frusciante e i Criticoni" per My Physical Movie Library.

Legge, una volta al mese, SOLO gli elenchi dei film di filmcriticoni.it (indice indipendente dei
film discussi nei video di Federico Frusciante e dei Criticoni) e scrive nell'app un indice compatto:
per ogni film titolo, anno, regista, giudizio complessivo, numero di video e di menzioni, indirizzo
della sua pagina. Le frasi trascritte delle menzioni NON vengono copiate: per quelle l'app rimanda
alla pagina del film sul sito.

Uso:
  python tools/aggiorna_criticoni.py index.html                 # dal sito (una pagina al secondo)
  python tools/aggiorna_criticoni.py index.html --local CARTELLA # da pagine salvate (c-1.html, f-1.html, …)

Copia di sicurezza: l'indice viene salvato anche in data/criticoni.json.gz, accanto a index.html.
Se il sito non risponde o cambia struttura (troppo pochi film), lo script rimette nell'app l'ultima
copia salvata invece di fermarsi: i giudizi raccolti non si perdono, anche caricando un index.html nuovo.
Solo se manca anche la copia si ferma con un errore, SENZA modificare index.html.
"""
import base64, datetime, gzip, html, json, os, re, sys, time, urllib.request
from html.parser import HTMLParser

BASE = 'https://filmcriticoni.it'
SOURCES = {'c': '/', 'f': '/frusciante'}           # c = Criticoni, f = Frusciante
UA = 'MyPhysicalMovieLibrary-index/1.0 (indice personale aggiornato una volta al mese)'
SENT = {'positivo': 1, 'negativo': -1, 'misto': 0}
MIN_FILMS = {'c': 300, 'f': 1000}                   # sotto queste soglie qualcosa non va
HREF_RE = re.compile(r'^(?:https?://(?:www\.)?filmcriticoni\.it)?/(frusciante/)?film/([a-z0-9][a-z0-9-]*)/?$')
PAGE_RE = re.compile(r'[?&]page=(\d+)')


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
                self._cur = {'fr': bool(m.group(1)), 'slug': m.group(2), 'chunks': [], 'alt': ''}
                self._depth = 1
                return
            pm = PAGE_RE.search(href)
            if pm: self.pages.add(int(pm.group(1)))
        if self._cur is not None:
            if tag == 'a': self._depth += 1
            if tag == 'img' and a.get('alt') and not self._cur['alt']: self._cur['alt'] = a['alt'].strip()

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
    return [c['slug'], html.unescape(title), year, html.unescape(director), sent, vid, men]


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
        n = 0
        for c in p.cards:
            if (src == 'f') != c['fr']: continue        # solo le schede della sezione giusta
            row = parse_card(c)
            if row and row[0] not in seen:
                seen.add(row[0]); films.append(row); n += 1
        print(f'  {"Criticoni" if src == "c" else "Frusciante"} pagina {page}/{last}: {n} film')
        empty = empty + 1 if n == 0 else 0
        if empty >= 2: break
        page += 1
    return films


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
    data = {'v': 1, 'built': built, 'site': BASE}
    for src in ('c', 'f'):
        print(f'Leggo gli elenchi: {"Criticoni" if src == "c" else "Frusciante"}…')
        try:
            data[src] = crawl(src, local=local, delay=0 if local else 1.0)
        except Exception as e:
            restore_backup(html_path, f'il sito non risponde ({e})')
        if len(data[src]) < mins[src]:
            restore_backup(html_path, f'trovati solo {len(data[src])} film per {"i Criticoni" if src == "c" else "Frusciante"} '
                                      f'(attesi almeno {mins[src]}): la struttura del sito potrebbe essere cambiata')
    size = embed(html_path, data, built)
    save_backup(html_path, data)
    print(f'Fatto: {len(data["c"])} film dei Criticoni e {len(data["f"])} di Frusciante, indice di {size // 1024} KB, data {built}.')


if __name__ == '__main__':
    main()
