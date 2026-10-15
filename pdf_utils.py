"""
Utility per estrarre la scadenza da PDF allegati agli interpelli.
Usato come fallback quando il testo dell'interpello non contiene una data leggibile.
"""
import io
import zipfile
from typing import Dict, List, Tuple

import requests
import pypdf

from filtering import estrai_scadenza

_DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

# Cache in-memory per evitare di scaricare lo stesso PDF più volte nella stessa run
_cache: Dict[str, str] = {}
# url ZIP → testo del PDF con la scadenza ('' incluso)
_cache_testi: Dict[str, str] = {}


def estrai_scadenza_da_pdf(url: str, extra_headers: dict = None) -> str:
    """Scarica il PDF all'URL e cerca la data di scadenza nel testo estratto.

    Ritorna 'DD/MM/YYYY' o '' su qualsiasi errore o PDF non testuale.
    """
    if not url:
        return ''
    if url in _cache:
        return _cache[url]

    result = _scarica_e_estrai(url, extra_headers)
    _cache[url] = result
    return result


def estrai_scadenza_da_zip_url(url: str, extra_headers: dict = None) -> str:
    """Scarica uno ZIP da URL (es. pre-signed S3) ed estrae la scadenza domanda
    da tutti i PDF contenuti. Ritorna il primo risultato non vuoto, o '' su errore."""
    return estrai_scadenza(testo_scadenza_da_zip_url(url, extra_headers))


def testo_scadenza_da_zip_url(url: str, extra_headers: dict = None) -> str:
    """Testo del primo PDF dello ZIP che contiene una scadenza domanda, o ''.
    Serve anche a estrarre i dettagli dell'interpello (ora, periodo, ore, sede)."""
    if not url:
        return ''
    if url not in _cache_testi:
        _cache_testi[url] = next((t for _, t in _testi_zip(url, extra_headers) if estrai_scadenza(t)), '')
    return _cache_testi[url]


def testo_da_zip_url(url: str, extra_headers: dict = None) -> str:
    """Nomi dei file e testo dei PDF contenuti nello ZIP (es. allegati Argo), per
    cercare il codice classe di concorso quando la descrizione dell'atto non lo dice.
    '' su errore."""
    if not url:
        return ''
    return ' '.join(f"{nome} {testo}" for nome, testo in _testi_zip(url, extra_headers))


def _scarica_e_estrai(url: str, extra_headers: dict = None) -> str:
    try:
        headers = dict(_DEFAULT_HEADERS)
        if extra_headers:
            headers.update(extra_headers)
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        if 'pdf' not in resp.headers.get('Content-Type', '').lower() and not url.lower().endswith('.pdf'):
            return ''
        reader = pypdf.PdfReader(io.BytesIO(resp.content))
        testo = ' '.join(page.extract_text() or '' for page in reader.pages)
        return estrai_scadenza(testo)
    except Exception:
        return ''


def _testi_zip(url: str, extra_headers: dict = None) -> List[Tuple[str, str]]:
    """[(nome_file, testo)] per ogni file dello ZIP; testo vuoto per i non-PDF o i PDF
    illeggibili. Lista vuota su errore di download."""
    try:
        headers = dict(_DEFAULT_HEADERS)
        if extra_headers:
            headers.update(extra_headers)
        resp = requests.get(url, headers=headers, timeout=60)
        resp.raise_for_status()
        risultati = []
        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
            for name in z.namelist():
                testo = ''
                if name.lower().endswith('.pdf'):
                    try:
                        reader = pypdf.PdfReader(io.BytesIO(z.read(name)))
                        testo = ' '.join(page.extract_text() or '' for page in reader.pages)
                    except Exception:
                        pass
                risultati.append((name, testo))
        return risultati
    except Exception:
        return []
