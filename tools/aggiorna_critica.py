#!/usr/bin/env python3
"""
Indice della critica per l'Atlante del Cinema.

Una volta al mese raccoglie da Wikidata (gratis, senza chiavi) i voti di Rotten Tomatoes (Tomatometer, in
percentuale) e di Metacritic per i film con un codice IMDb, e li salva in data/critica.json.gz. L'Atlante li
usa, con i voti IMDb e i giudizi di Frusciante e dei Criticoni, per i "capolavori assoluti".
Raccoglie anche, per le classifiche: incassi al botteghino (in dollari), numero di premi, Oscar ed Emmy vinti.

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
PREFIX psv: <http://www.wikidata.org/prop/statement/value/>
PREFIX wikibase: <http://wikiba.se/ontology#>
SELECT ?imdb ?score ?date WHERE {
  ?st pq:P447 wd:%s .
  ?film p:P444 ?st .
  ?st ps:P444 ?score .
  ?film wdt:P345 ?imdb .
  OPTIONAL { ?st pq:P585 ?date }
}"""


PFX = QUERY.split('SELECT')[0]
EXTRA = {   # classifiche: se una richiesta non riesce, le altre (e la critica) restano
  'box': ('incassi', PFX + 'SELECT ?imdb (MAX(?amt) AS ?n) WHERE { ?film wdt:P345 ?imdb ; p:P2142 ?st . ?st psv:P2142 ?v . ?v wikibase:quantityAmount ?amt ; wikibase:quantityUnit wd:Q4917 . FILTER(STRSTARTS(?imdb, "tt")) } GROUP BY ?imdb'),
  'aw': ('premi', PFX + 'SELECT ?imdb (COUNT(DISTINCT ?aw) AS ?n) WHERE { ?film wdt:P345 ?imdb ; wdt:P166 ?aw . FILTER(STRSTARTS(?imdb, "tt")) } GROUP BY ?imdb HAVING(COUNT(DISTINCT ?aw) >= 2)'),
  'osc': ('Oscar', PFX + 'SELECT ?imdb (COUNT(DISTINCT ?aw) AS ?n) WHERE { ?film wdt:P345 ?imdb ; wdt:P166 ?aw . ?aw (wdt:P31|wdt:P279|wdt:P361) wd:Q19020 . FILTER(STRSTARTS(?imdb, "tt")) } GROUP BY ?imdb'),
  'emmy': ('Emmy', PFX + 'SELECT ?imdb (COUNT(DISTINCT ?aw) AS ?n) WHERE { ?film wdt:P345 ?imdb ; wdt:P166 ?aw . ?aw (wdt:P31|wdt:P279|wdt:P361) wd:Q1044427 . FILTER(STRSTARTS(?imdb, "tt")) } GROUP BY ?imdb'),
  # cinema e serie italiane: 'ita' = in quanti paesi è prodotto un titolo che ha l'Italia tra i paesi (1 = solo Italia);
  # 'ita_l' = titoli italiani girati (anche) in italiano. L'Atlante considera italiano chi è in 'ita' con 1 oppure in 'ita_l'.
  'ita': ('produzioni italiane', PFX + 'SELECT ?imdb (COUNT(DISTINCT ?c) AS ?n) WHERE { ?film wdt:P345 ?imdb ; wdt:P495 wd:Q38 ; wdt:P495 ?c . FILTER(STRSTARTS(?imdb, "tt")) } GROUP BY ?imdb'),
  'ita_l': ('italiani in lingua italiana', PFX + 'SELECT ?imdb (COUNT(DISTINCT ?l) AS ?n) WHERE { ?film wdt:P345 ?imdb ; wdt:P495 wd:Q38 ; wdt:P364 wd:Q652 ; wdt:P364 ?l . FILTER(STRSTARTS(?imdb, "tt")) } GROUP BY ?imdb'),
  # riconoscimento internazionale: premi o candidature a Oscar, Golden Globe, BAFTA, Cannes (Palma d'Oro, Gran Premio), Venezia (Leone d'Oro), Berlino (Orso d'Oro), Emmy
  'intl': ('premi internazionali', PFX + 'SELECT ?imdb (COUNT(DISTINCT ?aw) AS ?n) WHERE { ?film wdt:P345 ?imdb . { ?film wdt:P166 ?aw } UNION { ?film wdt:P1411 ?aw } { ?aw (wdt:P31|wdt:P279|wdt:P361) ?g . VALUES ?g { wd:Q19020 wd:Q1011547 wd:Q732997 wd:Q42369 wd:Q49024 wd:Q130871 wd:Q1044427 wd:Q179808 wd:Q209459 wd:Q154590 } } UNION { VALUES ?aw { wd:Q179808 wd:Q209459 wd:Q154590 wd:Q844804 } } FILTER(STRSTARTS(?imdb, "tt")) } GROUP BY ?imdb'),
}


# Nuove serie e nuove stagioni dal calendario di TVmaze (gratis, senza chiavi): le puntate numero 1 di ogni stagione.
# Wikidata conosce solo l'inizio di una serie nuova, e spesso con giorni di ritardo; TVmaze ha il palinsesto giorno per giorno.
TVM_COUNTRIES = ['US', 'GB', 'IT', 'CA', 'AU', 'IE', 'DE', 'FR', 'ES', 'NL', 'SE', 'DK', 'NO', 'BE', 'NZ']
TVM_LANG = {'English', 'Italian', 'Spanish', 'French', 'German', 'Danish', 'Swedish', 'Norwegian', 'Dutch', 'Portuguese', 'Finnish', 'Icelandic', 'Polish'}


def tvmaze_premieres(since, until, get=None):
    """{imdb: (data, stagione)} per le prime puntate di stagione uscite tra since e until (date ISO)."""
    def _get(url):
        for k in range(4):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=40) as r:
                    return json.loads(r.read().decode('utf-8'))
            except urllib.error.HTTPError as e:
                if e.code == 404: return []
                time.sleep(10 if e.code == 429 else 3 * (k + 1))
            except Exception:
                time.sleep(3 * (k + 1))
        raise RuntimeError('TVmaze non risponde: ' + url)
    get = get or _get
    found, d, end, fails = {}, datetime.date.fromisoformat(since), datetime.date.fromisoformat(until), 0
    while d <= end:
        D = d.isoformat()
        for url in [f'https://api.tvmaze.com/schedule/web?date={D}'] + [f'https://api.tvmaze.com/schedule?country={c}&date={D}' for c in TVM_COUNTRIES]:
            try: eps = get(url) or []
            except Exception: fails += 1; continue
            for ep in eps:
                show = ep.get('show') or (ep.get('_embedded') or {}).get('show') or {}
                imdb = str((show.get('externals') or {}).get('imdb') or '')
                if ep.get('number') != 1 or not re.match(r'^tt\d+$', imdb) or ep.get('type', 'regular') != 'regular': continue
                if show.get('language') and show.get('language') not in TVM_LANG: continue
                if (show.get('type') or '') in ('Talk Show', 'News', 'Sports', 'Game Show', 'Award Show'): continue
                ad, sn = str(ep.get('airdate') or '')[:10], ep.get('season') or 1
                if not re.match(r'^\d{4}-\d\d-\d\d$', ad) or ad < since or ad > until: continue
                cc = {str(((show.get(k) or {}).get('country') or {}).get('code') or '') for k in ('network', 'webChannel')}
                ita = 'IT' in cc or show.get('language') == 'Italian'
                old = found.get(imdb)
                if not old or sn > old[1] or (sn == old[1] and ad < old[0]): found[imdb] = (ad, sn, ita or (old[2] if old else False))
            if get is _get: time.sleep(0.55)   # TVmaze: al massimo 20 richieste ogni 10 secondi
        d += datetime.timedelta(days=1)
    if fails > 40: raise RuntimeError(f'TVmaze: {fails} richieste fallite')
    return found


def ask(key, local=None):
    if local:
        path = os.path.join(local, f'q-{key}.json')
        if not os.path.exists(path): raise RuntimeError('risposta di prova mancante')
        return json.load(open(path, encoding='utf-8')), 'prova'
    errors = []
    for name, url in ENDPOINTS:
        for k in range(3):
            try:
                q = EXTRA[key][1] if key in EXTRA else QUERY % SOURCES[key][1]
                req = urllib.request.Request(url + '?' + urllib.parse.urlencode({'query': q}),
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
    out = {'v': 1, 'built': built, 'rt': res['rt'], 'mc': res['mc']}
    for key, (label, _) in EXTRA.items():
        try:
            j, via = ask(key, local); m = {}
            for b in j.get('results', {}).get('bindings', []):
                imdb, n = b.get('imdb', {}).get('value', ''), b.get('n', {}).get('value', '')
                try: v = int(float(n))
                except ValueError: continue
                if re.match(r'^tt\d+$', imdb) and v > 0: m[imdb] = v
            if key in ('ita', 'ita_l') and len(m) < 2000: print(f'  {label}: solo {len(m)} titoli, elenco non credibile: lo salto'); continue
            if key in ('osc', 'emmy', 'intl') and len(m) < (300 if key == 'intl' else 30): print(f'  {label}: solo {len(m)} titoli, classifica non credibile: la salto'); continue
            out[key] = m; print(f'  {label}: {len(m)} titoli (da {via})')
        except Exception as e:
            print(f'  {label}: non disponibile stanotte ({str(e)[:80]}), si riprova la prossima')
    # uscite dell'ultimo mese, per la home degli Atlanti: pronte all'apertura, senza far aspettare Wikidata al telefono
    since = (datetime.date.fromisoformat(built) - datetime.timedelta(days=45)).isoformat()
    XSD = 'PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>\n'
    rng = f'FILTER(?d >= "{since}T00:00:00Z"^^xsd:dateTime && ?d <= "{built}T23:59:59Z"^^xsd:dateTime)'
    MQ = {'mese': ('uscite del mese (film)', PFX + XSD + 'SELECT ?imdb ?d ?pl WHERE { ?f wdt:P345 ?imdb . FILTER(STRSTARTS(?imdb, "tt")) ?f p:P577 ?st . ?st ps:P577 ?d . ' + rng + ' OPTIONAL { ?st pq:P291 ?pl } }'),
          'mese_s': ('uscite del mese (serie)', PFX + XSD + 'SELECT ?imdb ?d WHERE { ?f wdt:P345 ?imdb . FILTER(STRSTARTS(?imdb, "tt")) ?f wdt:P580 ?d . ' + rng + ' }')}
    for key, (label, q) in MQ.items():
        try:
            EXTRA[key] = (label, q); j, via = ask(key, local); it, anyd = {}, {}
            for b in j.get('results', {}).get('bindings', []):
                imdb, d = b.get('imdb', {}).get('value', ''), str(b.get('d', {}).get('value', ''))[:10]
                if not re.match(r'^tt\d+$', imdb) or not re.match(r'^\d{4}-\d\d-\d\d$', d) or d < since or d > built: continue
                m = it if str(b.get('pl', {}).get('value', '')).endswith('/Q38') else anyd
                if imdb not in m or d < m[imdb]: m[imdb] = d
            res_m = {i: it.get(i) or anyd.get(i) for i in set(it) | set(anyd)}   # la data italiana se c'è, altrimenti la prima uscita
            if len(res_m) < 20: print(f'  {label}: solo {len(res_m)} titoli, non credibile: la salto'); continue
            out[key] = res_m; print(f'  {label}: {len(res_m)} titoli (da {via})')
        except Exception as e:
            print(f'  {label}: non disponibile stanotte ({str(e)[:80]}), l\'app le chiederà da sola')
    # italiani usciti nel mese ma ancora senza codice IMDb su Wikidata (succede spesso nelle prime settimane):
    # titolo italiano + data; l'app li cerca nel suo indice per titolo e anno
    TQ = {'mese_t': ('uscite italiane senza codice IMDb (film)', PFX + XSD + 'PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\nSELECT ?f ?lab ?d WHERE { VALUES ?c { wd:Q11424 wd:Q24869 wd:Q506240 wd:Q202866 wd:Q93204 } ?f wdt:P31 ?c ; wdt:P495 wd:Q38 ; p:P577 ?st . ?st ps:P577 ?d . ' + rng + ' ?f rdfs:label ?lab . FILTER(LANG(?lab) = "it") FILTER NOT EXISTS { ?f wdt:P345 ?x } }'),
          'mese_st': ('uscite italiane senza codice IMDb (serie)', PFX + XSD + 'PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\nSELECT ?f ?lab ?d WHERE { VALUES ?c { wd:Q5398426 wd:Q1259759 wd:Q526877 } ?f wdt:P31 ?c ; wdt:P495 wd:Q38 . { ?f wdt:P580 ?d } UNION { ?f wdt:P577 ?d } ' + rng + ' ?f rdfs:label ?lab . FILTER(LANG(?lab) = "it") FILTER NOT EXISTS { ?f wdt:P345 ?x } }')}
    for key, (label, q) in TQ.items():
        try:
            EXTRA[key] = (label, q); j, via = ask(key, local); seen = {}
            for b in j.get('results', {}).get('bindings', []):
                f, lab, d = b.get('f', {}).get('value', ''), str(b.get('lab', {}).get('value', '')).strip(), str(b.get('d', {}).get('value', ''))[:10]
                if not lab or not re.match(r'^\d{4}-\d\d-\d\d$', d) or d < since or d > built: continue
                if f not in seen or d < seen[f][2]: seen[f] = [lab, int(d[:4]), d]
            out[key] = sorted(seen.values(), key=lambda r: r[2], reverse=True)[:300]
            print(f'  {label}: {len(out[key])} titoli (da {via})')
        except Exception as e:
            print(f'  {label}: non disponibile stanotte ({str(e)[:80]})')
    # serie: aggiungo le nuove stagioni (e le serie nuove che Wikidata non ha ancora) dal calendario di TVmaze
    try:
        tv = tvmaze_premieres(since, built)
        ms, sn = dict(out.get('mese_s') or {}), {}
        n_it = 0
        for imdb, (ad, s, ita) in tv.items():
            if s > 1 or imdb not in ms: ms[imdb] = ad
            elif ad < ms[imdb]: ms[imdb] = ad
            if s > 1: sn[imdb] = s
            if ita:   # serie di una rete o piattaforma italiana: italiana anche se Wikidata non lo sa ancora
                for k in ('ita', 'ita_l'):
                    if isinstance(out.get(k), dict) and not out[k].get(imdb): out[k][imdb] = 1; n_it += 1 if k == 'ita' else 0
        if len(ms) >= 20: out['mese_s'], out['mese_sn'] = ms, sn
        print(f'  nuove serie e nuove stagioni (TVmaze): {len(tv)} titoli, {len(sn)} nuove stagioni, {n_it} serie italiane aggiunte; uscite delle serie in tutto: {len(ms)}')
    except Exception as e:
        print(f'  TVmaze non disponibile stanotte ({str(e)[:80]}): restano le uscite di Wikidata')
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, 'wb') as f:
        f.write(gzip.compress(json.dumps(out, separators=(',', ':')).encode('utf-8'), 9))
    print(f'Fatto: {len(res["rt"])} film con Rotten Tomatoes e {len(res["mc"])} con Metacritic, data {built}.')


if __name__ == '__main__':
    main()
