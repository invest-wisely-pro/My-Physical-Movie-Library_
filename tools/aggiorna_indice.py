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

Uso:
  python aggiorna_indice.py index.html            # scarica i dati aggiornati
  python aggiorna_indice.py index.html --local DIR  # usa file .tsv.gz già scaricati
Solo libreria standard di Python 3.8+.
"""
import sys, os, re, gzip, io, base64, datetime, tempfile, urllib.request

BASE = 'https://datasets.imdbws.com/'
FILES = ['title.basics.tsv.gz', 'title.akas.tsv.gz', 'title.ratings.tsv.gz', 'title.crew.tsv.gz', 'name.basics.tsv.gz', 'title.principals.tsv.gz']
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
    cand = set()
    for line in open_tsv(paths['title.basics.tsv.gz']):
        p = line.rstrip('\n').split('\t')
        if len(p) > 4 and p[1] in ('movie', 'tvMovie') and p[4] == '0': cand.add(int(p[0][2:]))
    log('Candidati (movie/tvMovie non adulti):', len(cand))
    # 2) titoli italiani: principale = "imdbDisplay" (altrimenti il primo), gli altri come alias
    it = {}
    for line in open_tsv(paths['title.akas.tsv.gz']):
        p = line.rstrip('\n').split('\t')
        if len(p) < 6 or p[3] != 'IT': continue
        k = int(p[0][2:])
        if k not in cand: continue
        t = clean(p[2])
        if not t: continue
        rec = it.setdefault(k, [None, []])
        if 'imdbDisplay' in p[5] and rec[0] is None: rec[0] = t
        else: rec[1].append(t)
    log('Con titolo italiano:', len(it))
    # 3) dati del film
    rows = {}
    for line in open_tsv(paths['title.basics.tsv.gz']):
        p = line.rstrip('\n').split('\t')
        if len(p) < 9: continue
        k = int(p[0][2:])
        if k not in it: continue
        main, alts = it[k]
        if main is None:
            if not alts: continue
            main, alts = alts[0], alts[1:]
        prim = clean(p[2])
        en = prim if prim and prim.lower() != main.lower() else ''
        seen = {main.lower()}; al = []
        for a in alts:
            if a.lower() not in seen: seen.add(a.lower()); al.append(a)
        genres = ', '.join(GENRES[g] for g in clean(p[8]).split(',') if g in GENRES)
        rows[k] = [p[0][2:], main, en, clean(p[5]), clean(p[7]), genres, '0', '', '~'.join(al[:6]), '']
    del it, cand
    # 4) voti
    for line in open_tsv(paths['title.ratings.tsv.gz']):
        p = line.rstrip('\n').split('\t')
        k = int(p[0][2:])
        if k in rows: rows[k][7] = p[1]; rows[k][6] = p[2]
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
            if k not in rows: continue
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
        lines = [rows[k][0] + '|' + ','.join(b36(pos[n]) for n in ids if n in pos) for k, ids in sorted(cast.items())]
        cast_text = '\n'.join(nm[n] for n in order) + '\n#\n' + '\n'.join(l for l in lines if not l.endswith('|')) + '\n'
        log('Attori nel cast offline:', len(order))
    return out, len(rows), cast_text, len(cast)

def gz64(text):
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode='wb', compresslevel=9, mtime=0) as g: g.write(text.encode('utf-8'))
    return base64.b64encode(buf.getvalue()).decode('ascii')

def embed(html_path, text, cast_text=''):
    html = open(html_path, encoding='utf-8').read()
    b64 = gz64(text)
    today = datetime.date.today().isoformat()
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
                if nme != 'title.principals.tsv.gz': raise
                log('File del cast assente: aggiorno solo l\'indice dei film')
        text, n, cast_text, nc = build(paths)
    else:
        with tempfile.TemporaryDirectory() as d:
            text, n, cast_text, nc = build(download(d))
    if n < 50000: raise SystemExit(f'Indice sospetto ({n} film): non lo inserisco')
    if cast_text and nc < n * 0.5:
        log(f'Cast sospetto ({nc} film su {n}): non lo inserisco, aggiorno solo l\'indice'); cast_text = ''
    embed(html, text, cast_text)

if __name__ == '__main__': main()
