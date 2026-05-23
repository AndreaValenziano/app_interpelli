#!/usr/bin/env python3
"""
Costruisce scuole_bat.json: istituti BAT con primaria/infanzia e customerCode Argo.
Raggruppa per CODICEISTITUTORIFERIMENTO (non per singolo plesso).
Eseguire una tantum; verificare la lista con l'utente prima di usarla in produzione.

Uso: python3 build_scuole_bat.py
"""
import csv
import io
import json
import re
import sys
import time
from typing import Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# CSV MIUR open-data "Anagrafe scuole statali" — aggiornare all'inizio di ogni anno scolastico.
# Se l'URL restituisce 404, visitare https://dati.istruzione.it/opendata/opendata/catalogo/elements1/
# e cercare "SCUANAGRAFESTAT" per trovare il file dell'anno corrente.
MIUR_CSV_URL = "https://dati.istruzione.it/opendata/opendata/catalogo/elements1/SCUANAGRAFESTAT20252620250901.csv"

PROVINCIA_BAT = {"BT", "110", "BARLETTA-ANDRIA-TRANI", "BARLETTA ANDRIA TRANI"}

OUTPUT_FILE = "scuole_bat.json"
SLEEP_TRA_SCUOLE = 0.5

ARGO_RE = re.compile(r'customerCode=([A-Z]{2}\d+)', re.IGNORECASE)

# Mapping manuale: piattaforma + params per scuola (manuale vince sull'auto-crawling).
# Chiave: codMec (CODICEISTITUTORIFERIMENTO); valore: (piattaforma, params_dict).
# Aggiornare se una scuola cambia piattaforma.
MAPPING_MANUALE: Dict[str, tuple] = {
    # --- Argo ---
    "BTIC86200Q": ("argo", {"customerCode": "SC27220"}),
    "BTIC86300G": ("argo", {"customerCode": "SC26991"}),
    "BTIC86400B": ("argo", {"customerCode": "SC27353"}),
    "BTIC89300B": ("argo", {"customerCode": "SC28160"}),
    "BTIC8AK00P": ("argo", {"customerCode": "SC29430"}),
    "BTIC8AL00E": ("argo", {"customerCode": "SC29431"}),
    "BTIC8AM00A": ("argo", {"customerCode": "SC29432"}),
    "BTIC8AN006": ("argo", {"customerCode": "SC29433"}),
    "BTEE061002": ("argo", {"customerCode": "SE29246"}),
    "BTEE06400D": ("argo", {"customerCode": "SE6206"}),
    "BTIC8AD00A": ("argo", {"customerCode": "SC29283"}),
    "BTIC852005": ("argo", {"customerCode": "SC27240"}),
    "BTIC80000C": ("argo", {"customerCode": "SC21815"}),
    "BTIC801008": ("argo", {"customerCode": "SC12641"}),
    # --- Nuvola Madisoft ---
    "BTIC89200G": ("nuvola", {"codMiur": "BAIC89200V"}),
    # --- Trasparenzascuole.it (Axios) ---
    "BTIC866003": ("trasparenzascuole", {"codiceFiscale": "90091130725"}),
    "BTEE06900L": ("trasparenzascuole", {"codiceFiscale": "83004410722"}),
    "BTIC8AQ00N": ("trasparenzascuole", {"codiceFiscale": "92081880723"}),
    "BTIC85400R": ("trasparenzascuole", {"codiceFiscale": "90059340746"}),
    "BTIC8AJ00V": ("trasparenzascuole", {"codiceFiscale": "91121590722"}),
    "BTEE172009": ("trasparenzascuole", {"codiceFiscale": "83002530729"}),
    "BTEE173005": ("trasparenzascuole", {"codiceFiscale": "83001990726"}),
    # Spaggiari (JS-side, fuori scope), custom, sconosciute → piattaforma=null, non in mappa
}

_GRADI_TARGET = {'PRIMARIA', 'INFANZIA'}
_ALBO_KEYWORDS = {'albo', 'pretori', 'amministrazione-trasparente', 'portaleargo'}
_VALORI_VUOTI = {'non disponibile', 'nd', '-', 'n/a', '', 'non disp.', 'nessuno'}

_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36'
}


def scarica_csv(url: str) -> List[Dict]:
    print(f"Scarico CSV MIUR da {url} ...")
    resp = requests.get(url, headers=_HEADERS, timeout=60)
    resp.raise_for_status()
    for enc in ('utf-8-sig', 'utf-8', 'iso-8859-1', 'cp1252'):
        try:
            content = resp.content.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        content = resp.content.decode('iso-8859-1', errors='replace')
    for delim in (';', ',', '\t'):
        reader = csv.DictReader(io.StringIO(content), delimiter=delim)
        righe = list(reader)
        if righe and len(righe[0]) > 2:
            return righe
    print("❌ Impossibile parsare il CSV con delimitatori comuni (;, ',', \\t)")
    sys.exit(1)


def trova_colonna(riga: Dict, *chiavi: str) -> str:
    riga_upper = {k.strip().upper(): k for k in riga}
    for chiave in chiavi:
        if chiave.upper() in riga_upper:
            return riga_upper[chiave.upper()]
    return ''


def col_val(riga: Dict, *chiavi: str) -> str:
    col = trova_colonna(riga, *chiavi)
    val = riga.get(col, '').strip() if col else ''
    return '' if val.lower() in _VALORI_VUOTI else val


def filtra_bat(righe: List[Dict]) -> List[Dict]:
    if not righe:
        return []
    prima = righe[0]
    prov_col = trova_colonna(prima, 'CODICEPROVINCIA', 'SIGLAPROVINCIA', 'PROVINCIA',
                             'PROVSCUOLA', 'CODPROVSCUOLA',
                             'CODICEPROVINCIAISTITUZIONERIFEIRIMENTO',
                             'CODICEPROVINCIAISTITUZIONERIFIMENTO')
    if not prov_col:
        print("⚠️  Colonna provincia non trovata. Colonne disponibili:")
        print("   ", list(prima.keys()))
        sys.exit(1)
    return [r for r in righe if r.get(prov_col, '').strip().upper() in PROVINCIA_BAT]


def normalizza_url(url: str) -> Optional[str]:
    if not url or url.strip().lower() in _VALORI_VUOTI:
        return None
    url = url.strip()
    # Correggi schemi malformati: https// → https://  http// → http://
    url = re.sub(r'^(https?)/', r'\1:/', url)
    # Correggi ww. → www.
    url = re.sub(r'^ww\.', 'www.', url)
    if not re.match(r'^https?://', url):
        url = 'http://' + url
    return url


def raggruppa_per_istituto(righe: List[Dict]) -> Dict[str, Dict]:
    """Raggruppa i plessi BAT per codice istituto di riferimento."""
    istituti: Dict[str, Dict] = {}
    for r in righe:
        cod_ist = col_val(r, 'CODICEISTITUTORIFERIMENTO', 'CODICEISTRUZIONE')
        if not cod_ist:
            continue
        nome_ist = col_val(r, 'DENOMINAZIONEISTITUTORIFERIMENTO', 'DENOMINAZIONESCUOLA', 'DENOMINAZIONE')
        grado = col_val(r, 'DESCRIZIONETIPOLOGIAGRADOISTRUZIONESCUOLA',
                        'DESCRIZIONETIPOLOGIAGRADO', 'TIPOLOGIAGRADO',
                        'DESCRIZIONE_TIPOLOGIA_GRADO_ISTRUZIONE_SCUOLA')
        sito = col_val(r, 'SITOWEBSCUOLA', 'SITOWEB', 'URLISTITUZIONALE', 'SITO_WEB')
        pec = col_val(r, 'INDIRIZZOPECSCUOLA', 'PECISTITUZIONALE', 'EMAILSCUOLA')
        comune = col_val(r, 'DESCRIZIONECOMUNE', 'DENOMINAZIONECOMUNE', 'COMUNE')

        if cod_ist not in istituti:
            istituti[cod_ist] = {
                'codMec': cod_ist,
                'nome': nome_ist,
                'comune': comune,
                'gradi': set(),
                'siti_raw': set(),
                'pec': '',
            }
        ist = istituti[cod_ist]
        if grado:
            ist['gradi'].add(grado.upper())
        url_norm = normalizza_url(sito) if sito else None
        if url_norm:
            ist['siti_raw'].add(url_norm)
        if pec and not ist['pec']:
            ist['pec'] = pec
        if comune and not ist['comune']:
            ist['comune'] = comune
        if nome_ist and not ist['nome']:
            ist['nome'] = nome_ist

    return istituti


def ha_primaria_o_infanzia(gradi: Set[str]) -> bool:
    return any(t in g for g in gradi for t in _GRADI_TARGET)


def e_cpia(nome: str) -> bool:
    nome_u = nome.upper()
    return 'CPIA' in nome_u or 'CENTRO PROVINCIALE' in nome_u or 'CENTRO TERRIT' in nome_u


def trova_customer_code_argo(siti: List[str], cod_ist: str) -> Optional[str]:
    """Cerca customerCode: homepage + subpagine albo/pretori. Fallback: www.{codice}.edu.it."""
    urls_da_provare = list(siti)
    fallback = f"http://www.{cod_ist.lower()}.edu.it"
    if not any(u.lower().rstrip('/') == fallback.rstrip('/') for u in urls_da_provare):
        urls_da_provare.append(fallback)

    for url in urls_da_provare:
        cc = _crawla_sito(url)
        if cc:
            return cc
    return None


def _crawla_sito(url: str) -> Optional[str]:
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=15, allow_redirects=True)
        if resp.status_code >= 400:
            return None
        text = resp.text

        m = ARGO_RE.search(text)
        if m:
            return m.group(1).upper()

        soup = BeautifulSoup(text, 'html.parser')
        albo_links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            m = ARGO_RE.search(href)
            if m:
                return m.group(1).upper()
            if any(kw in href.lower() for kw in _ALBO_KEYWORDS):
                albo_links.append(href)

        # Segui i link albo (fino a 3) rimanendo sullo stesso dominio
        base_netloc = urlparse(resp.url).netloc
        for href in albo_links[:3]:
            if not href.startswith('http'):
                href = urljoin(resp.url, href)
            if urlparse(href).netloc != base_netloc:
                continue
            try:
                r2 = requests.get(href, headers=_HEADERS, timeout=15, allow_redirects=True)
                m = ARGO_RE.search(r2.text)
                if m:
                    return m.group(1).upper()
            except Exception:
                pass
            time.sleep(0.3)
    except Exception:
        pass
    return None


def main():
    try:
        righe = scarica_csv(MIUR_CSV_URL)
    except requests.HTTPError as e:
        print(f"❌ Errore download CSV MIUR: {e}")
        print("   Verifica che MIUR_CSV_URL in build_scuole_bat.py sia aggiornato.")
        print("   URL attuale:", MIUR_CSV_URL)
        sys.exit(1)

    bat = filtra_bat(righe)
    if not bat:
        print("❌ Nessuna scuola trovata per la provincia BAT. Verifica il CSV e il filtro provincia.")
        sys.exit(1)
    print(f"Trovati {len(bat)} plessi con provincia BAT")

    istituti = raggruppa_per_istituto(bat)
    print(f"Raggruppati in {len(istituti)} istituti di riferimento")

    # Filtra: solo primaria/infanzia, escludi CPIA
    target = {
        cod: ist for cod, ist in istituti.items()
        if ha_primaria_o_infanzia(ist['gradi']) and not e_cpia(ist.get('nome', ''))
    }
    print(f"Istituti con primaria/infanzia (escluso CPIA): {len(target)}")

    scuole = []
    target_sorted = sorted(target.items())
    for i, (cod, ist) in enumerate(target_sorted, 1):
        siti = sorted(ist['siti_raw'])
        nome = ist['nome'] or cod
        print(f"[{i:2d}/{len(target)}] {nome[:50]:<50}", end='  ', flush=True)

        customer_code = trova_customer_code_argo(siti, cod)
        if customer_code:
            print(f"→ Argo {customer_code}")
        else:
            print("→ non trovato")

        scuole.append({
            'codMec': cod,
            'nome': nome,
            'comune': ist['comune'],
            'siti': siti,
            'pec': ist['pec'],
            'gradi': sorted(ist['gradi']),
            'piattaforma': 'argo' if customer_code else None,
            'params': {'customerCode': customer_code} if customer_code else None,
        })
        time.sleep(SLEEP_TRA_SCUOLE)

    # Applica mapping manuale (vince sull'auto-crawling)
    n_overlay = 0
    for scuola in scuole:
        if scuola['codMec'] in MAPPING_MANUALE:
            piattaforma, params = MAPPING_MANUALE[scuola['codMec']]
            scuola['piattaforma'] = piattaforma
            scuola['params'] = params
            n_overlay += 1

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(scuole, f, ensure_ascii=False, indent=2)

    from collections import Counter
    platform_counts = Counter(s['piattaforma'] or 'null' for s in scuole)
    print(f"\n✅ Salvato {OUTPUT_FILE}: {len(scuole)} istituti ({n_overlay} da mapping manuale)")
    for plat, cnt in sorted(platform_counts.items()):
        print(f"   {plat}: {cnt}")
    print("⚠️  Verifica i params prima di usare in produzione.")


if __name__ == '__main__':
    main()
