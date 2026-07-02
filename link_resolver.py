"""
Risolutore di scadenze: segue il link di un interpello e cerca la data di scadenza
domanda nella pagina di dettaglio e nei suoi allegati (PDF).

Gestisce i casi reali osservati:
- link diretto a PDF (con o SENZA estensione .pdf — es. le pagine allegato di
  istruzionebat.it servono direttamente il PDF con Content-Type application/pdf);
- pagina HTML di dettaglio con la scadenza nel testo;
- pagina HTML con link ad allegati (pagine figlie WordPress, /wp-content/uploads/,
  allegati Nuvola) da scaricare e leggere come PDF (riconosciuti dai magic bytes).

NON gestisce (i fetcher hanno fallback dedicati o non ne hanno):
- portaleargo.it: SPA JavaScript, il GET restituisce solo l'app shell;
- trasparenzascuole.it: richiede sessione curl_cffi + WAF Cloudflare.

Va chiamato DOPO il dedup, solo per gli interpelli nuovi: ogni risoluzione può
costare fino a ~7 richieste HTTP.
"""
import io
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import pypdf
import requests
from bs4 import BeautifulSoup

from filtering import estrai_scadenza

_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

MAX_ALLEGATI_PER_PAGINA = 6
MAX_BYTES = 20 * 1024 * 1024

# Domini che il resolver generico non può gestire
_DOMINI_NON_RISOLVIBILI = ('portaleargo.it', 'trasparenzascuole.it')

# Parole in href/testo del link che suggeriscono un allegato di interpello
_KEYWORDS_ALLEGATO = (
    '.pdf', 'wp-content/uploads', 'allegat', 'interpello', 'timbro',
    'avviso', 'decreto', 'modulo', 'disponibilit', 'documento',
)
_SKIP_HREF = (
    'mailto:', 'tel:', 'javascript:', 'facebook.', 'twitter.', 'x.com',
    'whatsapp', 'telegram', 'linkedin', 'instagram', 'youtube',
    'privacy', 'cookie', '/category/', '/tag/', '/author/', '/feed',
)

# Cache in-memory per run: url → scadenza ('' incluso)
_cache: Dict[str, str] = {}


def risolvi_scadenza_da_link(url: str) -> str:
    """Segue il link dell'interpello e ritorna la scadenza 'DD/MM/YYYY' o ''."""
    if not url:
        return ''
    if url in _cache:
        return _cache[url]
    try:
        risultato = _risolvi(url)
    except Exception:
        risultato = ''
    _cache[url] = risultato
    return risultato


def _risolvi(url: str) -> str:
    low = url.lower()
    if any(d in low for d in _DOMINI_NON_RISOLVIBILI):
        return ''

    scaricato = _scarica(url)
    if scaricato is None:
        return ''
    body, content_type = scaricato

    if _sembra_pdf(body, content_type):
        return _scadenza_da_pdf_bytes(body)
    if 'html' not in content_type:
        return ''

    soup = BeautifulSoup(body, 'html.parser')
    contenuto = (soup.find('div', class_='entry-content') or soup.find('main')
                 or soup.find('article') or soup.body or soup)
    scad = estrai_scadenza(contenuto.get_text(separator=' ', strip=True))
    if scad:
        return scad

    # Livello 1: scarica gli allegati candidati e cerca nei PDF
    for cand in _link_allegati(contenuto, url):
        sub = _scarica(cand)
        if sub is None:
            continue
        b, ct = sub
        if _sembra_pdf(b, ct):
            scad = _scadenza_da_pdf_bytes(b)
        elif 'html' in ct:
            # pagina allegato che incapsula il PDF: cerca URL di file diretti
            scad = _scadenza_da_pdf_embedded(b, cand)
        else:
            scad = ''
        if scad:
            return scad
    return ''


def _scarica(url: str) -> Optional[Tuple[bytes, str]]:
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=30)
        resp.raise_for_status()
        if len(resp.content) > MAX_BYTES:
            return None
        return resp.content, (resp.headers.get('Content-Type') or '').lower()
    except Exception:
        return None


def _sembra_pdf(body: bytes, content_type: str) -> bool:
    return body[:5] == b'%PDF-' or 'pdf' in content_type


def _scadenza_da_pdf_bytes(body: bytes) -> str:
    try:
        reader = pypdf.PdfReader(io.BytesIO(body))
        testo = ' '.join(page.extract_text() or '' for page in reader.pages)
        return estrai_scadenza(testo)
    except Exception:
        return ''


def _scadenza_da_pdf_embedded(html_body: bytes, base_url: str) -> str:
    """Da una pagina HTML allegato, prova gli URL di file diretti (.pdf / uploads)."""
    try:
        html = html_body.decode('utf-8', errors='replace')
    except Exception:
        return ''
    urls = re.findall(r'https?://[^\s"\'<>]+?\.pdf', html, re.IGNORECASE)
    urls += re.findall(r'https?://[^\s"\'<>]+?/wp-content/uploads/[^\s"\'<>]+', html)
    visti = []
    for u in urls:
        if u in visti:
            continue
        visti.append(u)
        if len(visti) > 3:
            break
        sub = _scarica(u)
        if sub and _sembra_pdf(*sub):
            scad = _scadenza_da_pdf_bytes(sub[0])
            if scad:
                return scad
    return ''


def _link_allegati(contenuto, base_url: str) -> List[str]:
    """Link candidati ad allegati dentro il contenuto della pagina, in ordine di priorità:
    prima i file diretti (.pdf/uploads), poi le pagine figlie del post (allegati WP),
    poi i link con parole chiave da allegato."""
    diretti, figli, keyword = [], [], []
    base_norm = base_url.rstrip('/') + '/'
    for a in contenuto.find_all('a', href=True):
        href = urljoin(base_url, a['href'].strip())
        low = href.lower()
        if href.rstrip('/') == base_url.rstrip('/'):
            continue
        if any(s in low for s in _SKIP_HREF):
            continue
        if not urlparse(href).scheme.startswith('http'):
            continue
        if href in diretti or href in figli or href in keyword:
            continue
        testo_link = a.get_text(strip=True).lower()
        if low.endswith('.pdf') or 'wp-content/uploads' in low:
            diretti.append(href)
        elif href.startswith(base_norm):
            figli.append(href)
        elif any(k in low or k in testo_link for k in _KEYWORDS_ALLEGATO):
            keyword.append(href)
    return (diretti + figli + keyword)[:MAX_ALLEGATI_PER_PAGINA]
