#!/usr/bin/env python3
"""
Aggiorna l'indice IMDb offline di My Physical Movie Library.

Scarica i dati ufficiali di IMDb (https://datasets.imdbws.com, uso personale e
non commerciale), ricostruisce l'indice con le stesse regole dell'app e lo
inserisce nel file HTML indicato (di solito index.html).

Regole: film per il cinema o per la TV (movie, tvMovie), non per adulti, con un
titolo italiano registrato su IMDb (i film distribuiti in Italia).
Formato di ogni riga: id|titolo italiano|titolo originale|anno|durata|generi|voti|voto|alias~alias|regia
In un blocco separato: i primi 5 attori di ogni film (tabella dei nomi + riferimenti),
per avere offline anche le filmografie degli attori (ruoli principali).
In un altro blocco: le serie TV (tvSeries, tvMiniSeries) con titolo italiano, stagioni ed episodi:
id|titolo italiano|titolo originale|anno inizio|anno fine|stagioni|episodi|generi|voti|voto|alias|episodi per stagione (es. 7,13,13)

Uso:
  python aggiorna_indice.py index.html            # scarica i dati aggiornati
  python aggiorna_indice.py index.html --local DIR  # usa file .tsv.gz già scaricati
Solo libreria standard di Python 3.8+.
"""
import sys, os, re, gzip, io, base64, datetime, tempfile, urllib.request

BASE = 'https://datasets.imdbws.com/'
FILES = ['title.basics.tsv.gz', 'title.akas.tsv.gz', 'title.ratings.tsv.gz', 'title.crew.tsv.gz', 'name.basics.tsv.gz', 'title.principals.tsv.gz', 'title.episode.tsv.gz']
OPTIONAL = ('title.principals.tsv.gz', 'title.episode.tsv.gz')
CAST_PER_FILM = 5   # ruoli principali: i primi attori dei titoli di testa
GENRES = {'Drama':'Drammatico','Comedy':'Commedia','Romance':'Romantico','Crime':'Crime','Documentary':'Documentario','Action':'Azione',
  'Thriller':'Thriller','Adventure':'Avventura','Horror':'Horror','Mystery':'Giallo','Biography':'Biografico','Family':'Famiglia','Fantasy':'Fantasy',
  'History':'Storico','Sci-Fi':'Fantascienza','Animation':'Animazione','Music':'Musica','War':'Guerra','Western':'Western','Musical':'Musical',
  'Sport':'Sport','Film-Noir':'Noir','News':'News','Reality-TV':'Reality-TV','Talk-Show':'Talk-Show','Game-Show':'Game-Show'}

def log(*a): print(*a, flush=True)
def clean(s): return '' if s in (None, '\\N') else s.replace('|', '/').replace('~', '-').replace('\n', ' ').replace('\r', ' ').strip()

def open_tsv(path):
    f = gzip.open(path, 'rt', encoding='utf-8', newline='')
    next(f)   # intestazione
    return f

def find(local, name):
    for cand in (name, name.replace('.', '_', 1).replace('.tsv', '_tsv')):
        p = os.path.join(local, cand)
        if os.path.exists(p): return p
    raise FileNotFoundError(name)

def download(dest):
    paths = {}
    for name in FILES:
        p = os.path.join(dest, name); log('Scarico', name, '…')
        req = urllib.request.Request(BASE + name, headers={'User-Agent': 'MyPhysicalMovieLibrary-index-updater'})
        with urllib.request.urlopen(req, timeout=600) as r, open(p, 'wb') as out:
            while True:
                b = r.read(1 << 20)
                if not b: break
                out.write(b)
        paths[name] = p
    return paths

def build(paths):
    # 1) candidati: movie / tvMovie, non adulti
    cand, scand = set(), set()
    for line in open_tsv(paths['title.basics.tsv.gz']):
        p = line.rstrip('\n').split('\t')
        if len(p) > 4 and p[4] == '0':
            if p[1] in ('movie', 'tvMovie'): cand.add(int(p[0][2:]))
            elif p[1] in ('tvSeries', 'tvMiniSeries'): scand.add(int(p[0][2:]))
    log('Candidati (movie/tvMovie non adulti):', len(cand), '· serie:', len(scand))
    # 2) titoli italiani: principale = "imdbDisplay" (altrimenti il primo), gli altri come alias
    it, its = {}, {}
    for line in open_tsv(paths['title.akas.tsv.gz']):
        p = line.rstrip('\n').split('\t')
        if len(p) < 6 or p[3] != 'IT': continue
        k = int(p[0][2:])
        tgt = it if k in cand else its if k in scand else None
        if tgt is None: continue
        t = clean(p[2])
        if not t: continue
        rec = tgt.setdefault(k, [None, []])
        if 'imdbDisplay' in p[5] and rec[0] is None: rec[0] = t
        else: rec[1].append(t)
    log('Con titolo italiano:', len(it), '· serie:', len(its))
    # 3) dati del film (e delle serie)
    rows, srows = {}, {}
    for line in open_tsv(paths['title.basics.tsv.gz']):
        p = line.rstrip('\n').split('\t')
        if len(p) < 9: continue
        k = int(p[0][2:])
        is_ser = k in its
        if k not in it and not is_ser: continue
        main, alts = (its if is_ser else it)[k]
        if main is None:
            if not alts: continue
            main, alts = alts[0], alts[1:]
        prim = clean(p[2])
        en = prim if prim and prim.lower() != main.lower() else ''
        seen = {main.lower()}; al = []
        for a in alts:
            if a.lower() not in seen: seen.add(a.lower()); al.append(a)
        genres = ', '.join(GENRES[g] for g in clean(p[8]).split(',') if g in GENRES)
        if is_ser: srows[k] = [p[0][2:], main, en, clean(p[5]), clean(p[6]), {}, 0, genres, '0', '', '~'.join(al[:6])]
        else: rows[k] = [p[0][2:], main, en, clean(p[5]), clean(p[7]), genres, '0', '', '~'.join(al[:6]), '']
    del it, its, cand, scand
    # 3b) stagioni ed episodi delle serie
    if paths.get('title.episode.tsv.gz') and srows:
        for line in open_tsv(paths['title.episode.tsv.gz']):
            p = line.rstrip('\n').split('\t')
            if len(p) < 3: continue
            k = int(p[1][2:]) if p[1].startswith('tt') else -1
            if k in srows:
                srows[k][6] += 1
                if p[2].isdigit() and 0 < int(p[2]) < 200: srows[k][5][int(p[2])] = srows[k][5].get(int(p[2]), 0) + 1
    # 4) voti
    for line in open_tsv(paths['title.ratings.tsv.gz']):
        p = line.rstrip('\n').split('\t')
        k = int(p[0][2:])
        if k in rows: rows[k][7] = p[1]; rows[k][6] = p[2]
        elif k in srows: srows[k][9] = p[1]; srows[k][8] = p[2]
    # 5) regia
    need = {}
    for line in open_tsv(paths['title.crew.tsv.gz']):
        p = line.rstrip('\n').split('\t')
        k = int(p[0][2:])
        if k in rows and p[1] != '\\N':
            ids = p[1].split(',')[:2]; need[k] = ids   # al massimo 2 registi, come l'indice originale
    # 6) cast: primi attori di ogni film (attori e attrici, in ordine di titoli di testa)
    cast = {}
    if paths.get('title.principals.tsv.gz'):
        for line in open_tsv(paths['title.principals.tsv.gz']):
            p = line.split('\t', 4)
            if len(p) < 4 or p[3] not in ('actor', 'actress'): continue
            k = int(p[0][2:])
            if k not in rows and k not in srows: continue
            lst = cast.setdefault(k, [])
            if len(lst) < CAST_PER_FILM * 2: lst.append((int(p[1]), p[2]))
        for k in cast: cast[k] = [n for _, n in sorted(cast[k])[:CAST_PER_FILM]]
        log('Film con cast:', len(cast))
    names = {n for ids in need.values() for n in ids} | {n for ids in cast.values() for n in ids}
    nm = {}
    for line in open_tsv(paths['name.basics.tsv.gz']):
        p = line.split('\t', 2)
        if p[0] in names: nm[p[0]] = clean(p[1])
    for k, ids in need.items(): rows[k][9] = ', '.join(nm[i] for i in ids if nm.get(i))
    out = '\n'.join('|'.join(rows[k]) for k in sorted(rows)) + '\n'
    log('Film nell\'indice:', len(rows))
    # blocco cast: nomi (uno per riga, ordinati per uso), poi "#", poi id|riferimenti in base 36
    cast_text = ''
    if cast:
        use = {}
        for ids in cast.values():
            for n in ids:
                if nm.get(n): use[n] = use.get(n, 0) + 1
        order = sorted(use, key=lambda n: (-use[n], nm[n]))
        pos = {n: i for i, n in enumerate(order)}
        def b36(i):
            d = '0123456789abcdefghijklmnopqrstuvwxyz'; s = ''
            while True:
                s = d[i % 36] + s; i //= 36
                if not i: return s
        lines = [str(k).zfill(7) + '|' + ','.join(b36(pos[n]) for n in ids if n in pos) for k, ids in sorted(cast.items())]
        cast_text = '\n'.join(nm[n] for n in order) + '\n#\n' + '\n'.join(l for l in lines if not l.endswith('|')) + '\n'
        log('Attori nel cast offline:', len(order))
    series_text = ''
    if srows:
        def per_season(d):   # episodi di ogni stagione, dalla 1 all'ultima (0 se manca)
            return ','.join(str(d.get(i, 0)) for i in range(1, max(d) + 1)) if d else ''
        series_text = '\n'.join('|'.join([r[0], r[1], r[2], r[3], r[4], str(len(r[5]) or ''), str(r[6] or ''), r[7], r[8], r[9], r[10], per_season(r[5])]) for k, r in sorted(srows.items())) + '\n'
        log('Serie TV nell\'indice:', len(srows))
    return out, len(rows), cast_text, len(cast), series_text, len(srows)

def gz64(text):
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode='wb', compresslevel=9, mtime=0) as g: g.write(text.encode('utf-8'))
    return base64.b64encode(buf.getvalue()).decode('ascii')

def embed(html_path, text, cast_text='', series_text='', built=None):
    html = open(html_path, encoding='utf-8').read()
    b64 = gz64(text)
    today = built or datetime.date.today().isoformat()
    new, n = re.subn(r'<script type="text/plain" id="imdbIndexData"[^>]*>[^<]*</script>',
                     lambda m: f'<script type="text/plain" id="imdbIndexData" data-built="{today}">{b64}</script>', html, count=1)
    if n != 1: raise SystemExit('Blocco dell\'indice non trovato nel file HTML')
    if cast_text:
        cb = gz64(cast_text)
        tag = f'<script type="text/plain" id="imdbCastData" data-built="{today}">{cb}</script>'
        new2, m = re.subn(r'<script type="text/plain" id="imdbCastData"[^>]*>[^<]*</script>', lambda _: tag, new, count=1)
        if m == 0:   # prima volta: il blocco del cast va subito dopo quello dell'indice
            new2 = re.sub(r'(<script type="text/plain" id="imdbIndexData"[^>]*>[^<]*</script>)', lambda mm: mm.group(1) + '\n' + tag, new, count=1)
        new = new2
        log(f'Cast offline inserito ({len(cb) / 1048576:.2f} MB)')
    if series_text:
        sb = gz64(series_text)
        tag = f'<script type="text/plain" id="imdbSeriesData" data-built="{today}">{sb}</script>'
        new2, m = re.subn(r'<script type="text/plain" id="imdbSeriesData"[^>]*>[^<]*</script>', lambda _: tag, new, count=1)
        if m == 0: new2 = re.sub(r'(<script type="text/plain" id="imdbIndexData"[^>]*>[^<]*</script>)', lambda mm: mm.group(1) + '\n' + tag, new, count=1)
        new = new2
        log(f'Serie TV inserite ({len(sb) / 1048576:.2f} MB)')
    open(html_path, 'w', encoding='utf-8').write(new)
    log(f'Indice inserito in {html_path} (aggiornato al {today}, {len(b64) / 1048576:.2f} MB)')

def main():
    if len(sys.argv) < 2: raise SystemExit(__doc__)
    html = sys.argv[1]
    if '--local' in sys.argv:
        d = sys.argv[sys.argv.index('--local') + 1]
        paths = {}
        for nme in FILES:
            try: paths[nme] = find(d, nme)
            except FileNotFoundError:
                if nme not in OPTIONAL: raise
                log('File assente (facoltativo):', nme)
        text, n, cast_text, nc, series_text, ns = build(paths)
    else:
        with tempfile.TemporaryDirectory() as d:
            text, n, cast_text, nc, series_text, ns = build(download(d))
    if n < 50000: raise SystemExit(f'Indice sospetto ({n} film): non lo inserisco')
    if cast_text and nc < n * 0.5:
        log(f'Cast sospetto ({nc} film su {n}): non lo inserisco, aggiorno solo l\'indice'); cast_text = ''
    if series_text and ns < 1000:
        log(f'Serie sospette ({ns}): non le inserisco'); series_text = ''
    built = sys.argv[sys.argv.index('--date') + 1] if '--date' in sys.argv else None   # data reale dei dati (per file locali)
    embed(html, text, cast_text, series_text, built)

if __name__ == '__main__': main()

