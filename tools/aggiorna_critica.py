#!/usr/bin/env python3
"""
Indice della critica per l'Atlante del Cinema.

Una volta al mese raccoglie da Wikidata (gratis, senza chiavi) i voti di Rotten Tomatoes (Tomatometer, in
percentuale) e di Metacritic per tutti i film che hanno un codice IMDb, e li salva in data/critica.json.gz.
L'Atlante li usa, insieme ai voti IMDb e ai giudizi di Frusciante e dei Criticoni, per i "capolavori assoluti".

Uso:
  python tools/aggiorna_critica.py data/critica.json.gz                  # da Wikidata
  python tools/aggiorna_critica.py data/critica.json.gz --local CARTELLA # da risposte salvate (q-tt00.json, …)

Sicurezza: se Wikidata non risponde o restituisce troppo poco, il file del mese prima resta com'è.
"""
import datetime, gzip, json, os, re, sys, time, urllib.parse, urllib.request

ENDPOINT = 'https://query.wikidata.org/sparql'
UA = 'MyPhysicalMovieLibrary-Atlante/1.0 (indice personale aggiornato una volta al mese)'
RT, MC = 'Q105584', 'Q150248'                      # Rotten Tomatoes, Metacritic
PREFIXES = ['tt0' + str(i) for i in range(10)] + ['tt' + str(i) for i in range(1, 10)]   # 19 gruppi piccoli
MIN_RT = 3000                                       # sotto questa soglia qualcosa non va

QUERY = """SELECT ?imdb ?score ?by ?date WHERE {
  ?film wdt:P345 ?imdb . FILTER(STRSTARTS(?imdb, "%s"))
  ?film p:P444 ?st . ?st ps:P444 ?score ; pq:P447 ?by .
  VALUES ?by { wd:%s wd:%s }
  OPTIONAL { ?st pq:P585 ?date }
}"""


def ask(prefix, local=None, tries=4):
    if local:
        path = os.path.join(local, f'q-{prefix}.json')
        return json.load(open(path, encoding='utf-8')) if os.path.exists(path) else {'results': {'bindings': []}}
    url = ENDPOINT + '?' + urllib.parse.urlencode({'query': QUERY % (prefix, RT, MC), 'format': 'json'})
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/sparql-results+json'})
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception as e:
            if k == tries - 1: raise
            print(f'  {prefix}: nuovo tentativo tra {10 * (k + 1)} s ({e})'); time.sleep(10 * (k + 1))


def parse(binds, rt, mc, dates):
    for b in binds:
        imdb = b.get('imdb', {}).get('value', ''); score = b.get('score', {}).get('value', '').strip()
        by = b.get('by', {}).get('value', '').rsplit('/', 1)[-1]; date = b.get('date', {}).get('value', '')
        if not re.match(r'^tt\d+$', imdb) or not score: continue
        if by == RT:
            m = re.match(r'^(\d{1,3})\s*%$', score)          # solo il Tomatometer in percentuale, mai le medie "7.6/10"
            if not m or int(m.group(1)) > 100: continue
            val, key = int(m.group(1)), ('rt', imdb)
        elif by == MC:
            m = re.match(r'^(\d{1,3})(?:\s*/\s*100)?$', score)
            if not m or int(m.group(1)) > 100: continue
            val, key = int(m.group(1)), ('mc', imdb)
        else:
            continue
        if key in dates and dates[key] > date: continue   # si tiene il valore più recente
        dates[key] = date
        (rt if key[0] == 'rt' else mc)[imdb] = val


def main():
    args = sys.argv[1:]
    if not args: print(__doc__); sys.exit(2)
    out = args[0]
    local = args[args.index('--local') + 1] if '--local' in args else None
    built = args[args.index('--date') + 1] if '--date' in args else datetime.date.today().isoformat()
    min_rt = 1 if '--no-min' in args else MIN_RT
    rt, mc, dates = {}, {}, {}
    try:
        for p in PREFIXES:
            j = ask(p, local)
            n0 = len(rt) + len(mc); parse(j.get('results', {}).get('bindings', []), rt, mc, dates)
            print(f'  {p}: {len(rt) + len(mc) - n0} voti')
            if not local: time.sleep(2)
    except Exception as e:
        print(f'ATTENZIONE: Wikidata non risponde ({e}).', 'Il file del mese prima resta com\'è.' if os.path.exists(out) else '')
        sys.exit(0 if os.path.exists(out) else 1)
    if len(rt) < min_rt:
        print(f'ATTENZIONE: trovati solo {len(rt)} voti di Rotten Tomatoes (attesi almeno {min_rt}).', 'Il file del mese prima resta com\'è.' if os.path.exists(out) else '')
        sys.exit(0 if os.path.exists(out) else 1)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, 'wb') as f:
        f.write(gzip.compress(json.dumps({'v': 1, 'built': built, 'rt': rt, 'mc': mc}, separators=(',', ':')).encode('utf-8'), 9))
    print(f'Fatto: {len(rt)} film con Rotten Tomatoes e {len(mc)} con Metacritic, data {built}.')


if __name__ == '__main__':
    main()
