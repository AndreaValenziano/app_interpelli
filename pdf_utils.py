"""
Utility per estrarre la scadenza da PDF allegati agli interpelli.
Usato come fallback quando il testo dell'interpello non contiene una data leggibile.
"""
import io
from typing import Dict

import requests
import pypdf

from filtering import estrai_scadenza

_DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

# Cache in-memory per evitare di scaricare lo stesso PDF più volte nella stessa run
_cache: Dict[str, str] = {}


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
