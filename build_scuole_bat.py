#!/usr/bin/env python3
"""
Costruisce scuole_bat.json: lista scuole statali nella provincia BAT con customerCode Argo.
Eseguire una tantum, verificare la lista con l'utente prima di usarla in produzione.

Uso: python3 build_scuole_bat.py
"""
import csv
import io
import json
import re
import sys
import time
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

# CSV MIUR open-data "Anagrafe scuole statali" — aggiornare all'inizio di ogni anno scolastico.
# Se l'URL restituisce 404, visitare https://dati.istruzione.it/opendata/opendata/catalogo/elements1/
# e cercare "SCUANAGRAFESTAT" per trovare il file dell'anno corrente.
MIUR_CSV_URL = "https://dati.istruzione.it/opendata/opendata/catalogo/elements1/SCUANAGRAFESTAT20252620250901.csv"

# Codice provincia BAT (alfanumerico MIUR e codice ISTAT)
PROVINCIA_BAT = {"BT", "110", "BARLETTA-ANDRIA-TRANI", "BARLETTA ANDRIA TRANI"}

OUTPUT_FILE = "scuole_bat.json"
SLEEP_TRA_SCUOLE = 0.5

ARGO_RE = re.compile(r'customerCode=([A-Z]{2}\d+)', re.IGNORECASE)


def scarica_csv(url: str) -> List[Dict]:
    print(f"Scarico CSV MIUR da {url} ...")
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    resp = requests.get(url, headers=headers, timeout=60)
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
    """Cerca la prima colonna che corrisponde a una delle chiavi (case-insensitive)."""
    riga_upper = {k.strip().upper(): k for k in riga}
    for chiave in chiavi:
        if chiave.upper() in riga_upper:
            return riga_upper[chiave.upper()]
    return ''


def filtra_bat(righe: List[Dict]) -> List[Dict]:
    if not righe:
        return []
    prima = righe[0]
    prov_col = trova_colonna(prima, 'CODICEPROVINCIA', 'SIGLAPROVINCIA', 'PROVINCIA',
                             'PROVSCUOLA', 'SIGLAPROVINCIA', 'CODPROVSCUOLA')
    if not prov_col:
        print("⚠️  Colonna provincia non trovata. Colonne disponibili:")
        print("   ", list(prima.keys()))
        sys.exit(1)
    return [r for r in righe if r.get(prov_col, '').strip().upper() in PROVINCIA_BAT]


_VALORI_VUOTI = {'non disponibile', 'nd', '-', 'n/a', ''}


def col_val(riga: Dict, *chiavi: str) -> str:
    col = trova_colonna(riga, *chiavi)
    val = riga.get(col, '').strip() if col else ''
    return '' if val.lower() in _VALORI_VUOTI else val


def trova_customer_code_argo(sito: str) -> Optional[str]:
    """Cerca customerCode Argo nel sito della scuola (home page e link di primo livello)."""
    if not sito:
        return None
    if not sito.startswith('http'):
        sito = 'http://' + sito
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36'}
        resp = requests.get(sito, headers=headers, timeout=15, allow_redirects=True)
        text = resp.text
        m = ARGO_RE.search(text)
        if m:
            return m.group(1).upper()
        # Prova a seguire i link che citano "albo"
        soup = BeautifulSoup(text, 'html.parser')
        for a in soup.find_all('a', href=True):
            href = a['href']
            if 'portaleargo' in href.lower() or ('albo' in href.lower() and 'pretori' in href.lower()):
                m = ARGO_RE.search(href)
                if m:
                    return m.group(1).upper()
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
    print(f"Trovate {len(bat)} scuole con provincia BAT")

    scuole = []
    for i, r in enumerate(bat, 1):
        cod = col_val(r, 'CODICESCUOLA', 'CODSCUOLA', 'CODICE_SCUOLA')
        nome = col_val(r, 'DENOMINAZIONESCUOLA', 'DENOMINAZIONE', 'NOMEISTSCUOLA')
        comune = col_val(r, 'DESCRIZIONECOMUNE', 'DENOMINAZIONECOMUNE', 'COMUNE')
        sito = col_val(r, 'SITOWEBSCUOLA', 'SITOWEB', 'URLISTITUZIONALE', 'SITO_WEB')
        pec = col_val(r, 'INDIRIZZOPECSCUOLA', 'PECISTITUZIONALE', 'EMAILSCUOLA', 'INDIRIZZOEMAILSCUOLA')

        print(f"[{i:2d}/{len(bat)}] {nome[:50]:<50} ({comune})", end='  ', flush=True)

        customer_code = trova_customer_code_argo(sito)
        if customer_code:
            print(f"→ Argo {customer_code}")
        else:
            print("→ non-Argo")

        scuole.append({
            'codMec': cod,
            'nome': nome,
            'comune': comune,
            'sito': sito,
            'pec': pec,
            'customerCode': customer_code,
            'piattaforma': 'argo' if customer_code else None,
        })
        time.sleep(SLEEP_TRA_SCUOLE)

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(scuole, f, ensure_ascii=False, indent=2)

    argo_count = sum(1 for s in scuole if s['customerCode'])
    print(f"\n✅ Salvato {OUTPUT_FILE}: {len(scuole)} scuole, {argo_count} con customerCode Argo")
    print("⚠️  Verifica i customerCode prima di usare in produzione.")


if __name__ == '__main__':
    main()
