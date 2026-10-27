#!/usr/bin/env python3
"""
Indice della critica per l'Atlante del Cinema.

Una volta al mese raccoglie da Wikidata (gratis, senza chiavi) i voti di Rotten Tomatoes (Tomatometer, in
percentuale) e di Metacritic per i film con un codice IMDb, e li salva in data/critica.json.gz. L'Atlante li
usa, con i voti IMDb e i giudizi di Frusciante e dei Criticoni, per i "capolavori assoluti".

Due richieste leggere (una per Rotten Tomatoes, una per Metacritic) che partono dai voti, non da tutti i film.
Prima su QLever (motore veloce sui dati di Wikidata), poi, se non risponde, sul servizio ufficiale di Wikidata.

Uso:
  python tools/aggiorna_critica.py data/critica.json.gz
  python tools/aggiorna_critica.py data/critica.json.gz --local CARTELLA   # risposte salvate: q-rt.json e q-mc.json

Sicurezza: se nessun servizio risponde, o i voti sono troppo pochi, il file del mese prima resta com'è.
"""
import datetime, gzip, json, os, re, sys, time, urllib.parse, urllib.request

UA = 'MyPhysicalMovieLibrary-Atlante/1.1 (indice personale aggiornato una volta al mese)'
ENDPOINTS = [('QLever', 'https://qlever.cs.uni-freiburg.de/api/wikidata'), ('Wikidata', 'https://query.wikidata.org/sparql')]
SOURCES = {'rt': ('Rotten Tomatoes', 'Q105584'), 'mc': ('Metacritic', 'Q150248')}
MIN_RT = 3000
QUERY = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX p: <http://www.wikidata.org/prop/>
PREFIX ps: <http://www.wikidata.org/prop/statement/>
PREFIX pq: <http://www.wikidata.org/prop/qualifier/>
SELECT ?imdb ?score ?date WHERE {
  ?st pq:P447 wd:%s .
  ?film p:P444 ?st .
  ?st ps:P444 ?score .
  ?film wdt:P345 ?imdb .
  OPTIONAL { ?st pq:P585 ?date }
}"""


def ask(key, local=None):
    if local:
        path = os.path.join(local, f'q-{key}.json')
        if not os.path.exists(path): raise RuntimeError('risposta di prova mancante')
        return json.load(open(path, encoding='utf-8')), 'prova'
    errors = []
    for name, url in ENDPOINTS:
        for k in range(3):
            try:
                req = urllib.request.Request(url + '?' + urllib.parse.urlencode({'query': QUERY % SOURCES[key][1]}),
                                             headers={'User-Agent': UA, 'Accept': 'application/sparql-results+json'})
                with urllib.request.urlopen(req, timeout=180) as r:
                    j = json.loads(r.read().decode('utf-8'))
                if 'results' in j: return j, name
                errors.append(f'{name}: risposta senza risultati')
            except Exception as e:
                errors.append(f'{name}: {e}')
                time.sleep(5 * (k + 1))
    raise RuntimeError(' | '.join(errors[-3:]))


def parse(key, binds, out, dates):
    for b in binds:
        imdb = b.get('imdb', {}).get('value', ''); score = b.get('score', {}).get('value', '').strip(); date = b.get('date', {}).get('value', '')
        if not re.match(r'^tt\d+$', imdb) or not score: continue
        if key == 'rt':
            m = re.match(r'^(\d{1,3})\s*%$', score)                     # solo il Tomatometer in percentuale, mai le medie "7.6/10"
        else:
            m = re.match(r'^(\d{1,3})(?:\s*/\s*100)?$', score)
        if not m or int(m.group(1)) > 100: continue
        if imdb in dates and dates[imdb] > date: continue                # si tiene il valore più recente
        dates[imdb] = date; out[imdb] = int(m.group(1))


def main():
    args = sys.argv[1:]
    if not args: print(__doc__); sys.exit(2)
    out_path = args[0]
    local = args[args.index('--local') + 1] if '--local' in args else None
    built = args[args.index('--date') + 1] if '--date' in args else datetime.date.today().isoformat()
    min_rt = 1 if '--no-min' in args else MIN_RT
    keep = 'Il file del mese prima resta com\'è.' if os.path.exists(out_path) else ''
    res = {'rt': {}, 'mc': {}}
    for key in ('rt', 'mc'):
        try:
            j, via = ask(key, local)
        except Exception as e:
            print(f'ATTENZIONE: {SOURCES[key][0]}: nessun servizio ha risposto ({e}). {keep}'); sys.exit(0 if keep else 1)
        parse(key, j.get('results', {}).get('bindings', []), res[key], {})
        print(f'  {SOURCES[key][0]}: {len(res[key])} film (da {via})')
    if len(res['rt']) < min_rt:
        print(f'ATTENZIONE: solo {len(res["rt"])} voti di Rotten Tomatoes (attesi almeno {min_rt}). {keep}'); sys.exit(0 if keep else 1)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, 'wb') as f:
        f.write(gzip.compress(json.dumps({'v': 1, 'built': built, 'rt': res['rt'], 'mc': res['mc']}, separators=(',', ':')).encode('utf-8'), 9))
    print(f'Fatto: {len(res["rt"])} film con Rotten Tomatoes e {len(res["mc"])} con Metacritic, data {built}.')


if __name__ == '__main__':
    main()
