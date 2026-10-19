#!/usr/bin/env python3
"""
Aggiorna l'indice IMDb offline di My Physical Movie Library.

Scarica i dati ufficiali di IMDb (https://datasets.imdbws.com, uso personale e
non commerciale), ricostruisce l'indice con le stesse regole dell'app e lo
inserisce nel file HTML indicato (di solito index.html).

Regole: film per il cinema o per la TV (movie, tvMovie), non per adulti, con un
titolo italiano registrato su IMDb (i film distribuiti in Italia).
Formato di ogni riga: id|titolo italiano|titolo originale|anno|durata|generi|voti|voto|alias~alias|regia

Uso:
  python aggiorna_indice.py index.html            # scarica i dati aggiornati
  python aggiorna_indice.py index.html --local DIR  # usa file .tsv.gz già scaricati
Solo libreria standard di Python 3.8+.
"""
import sys, os, re, gzip, io, base64, datetime, tempfile, urllib.request

BASE = 'https://datasets.imdbws.com/'
FILES = ['title.basics.tsv.gz', 'title.akas.tsv.gz', 'title.ratings.tsv.gz', 'title.crew.tsv.gz', 'name.basics.tsv.gz']
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
    names = {n for ids in need.values() for n in ids}
    nm = {}
    for line in open_tsv(paths['name.basics.tsv.gz']):
        p = line.split('\t', 2)
        if p[0] in names: nm[p[0]] = clean(p[1])
    for k, ids in need.items(): rows[k][9] = ', '.join(nm[i] for i in ids if nm.get(i))
    out = '\n'.join('|'.join(rows[k]) for k in sorted(rows)) + '\n'
    log('Film nell\'indice:', len(rows))
    return out, len(rows)

def embed(html_path, text):
    html = open(html_path, encoding='utf-8').read()
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode='wb', compresslevel=9, mtime=0) as g: g.write(text.encode('utf-8'))
    b64 = base64.b64encode(buf.getvalue()).decode('ascii')
    today = datetime.date.today().isoformat()
    new, n = re.subn(r'<script type="text/plain" id="imdbIndexData"[^>]*>[^<]*</script>',
                     lambda m: f'<script type="text/plain" id="imdbIndexData" data-built="{today}">{b64}</script>', html, count=1)
    if n != 1: raise SystemExit('Blocco dell\'indice non trovato nel file HTML')
    open(html_path, 'w', encoding='utf-8').write(new)
    log(f'Indice inserito in {html_path} (aggiornato al {today}, {len(b64) / 1048576:.2f} MB)')

def main():
    if len(sys.argv) < 2: raise SystemExit(__doc__)
    html = sys.argv[1]
    if '--local' in sys.argv:
        d = sys.argv[sys.argv.index('--local') + 1]
        paths = {n: find(d, n) for n in FILES}
        text, n = build(paths)
    else:
        with tempfile.TemporaryDirectory() as d:
            text, n = build(download(d))
    if n < 50000: raise SystemExit(f'Indice sospetto ({n} film): non lo inserisco')
    embed(html, text)

if __name__ == '__main__': main()
