"""
Risolutore di scadenze: segue il link di un interpello e cerca la data di scadenza
domanda nella pagina di dettaglio e nei suoi allegati (PDF).

Gestisce i casi reali osservati:
- link diretto a PDF (con o SENZA estensione .pdf — es. le pagine allegato di
  istruzionebat.it servono direttamente il PDF con Content-Type application/pdf);
- pagina HTML di dettaglio con la scadenza nel testo;
- pagina HTML con link ad allegati (pagine figlie WordPress, /wp-content/uploads/,
  allegati Nuvola) da scaricare e leggere come PDF (riconosciuti dai magic bytes).

Per portaleargo.it (SPA JavaScript, il GET restituisce solo l'app shell) i deep-link
`dettaglio-atto?customerCode=X&id=Y` vengono risolti tramite l'API REST pubblica:
endpoint allegati → ZIP → PDF. `argo_archiviato()` rileva inoltre gli atti non più
in pubblicazione (spariti dal listing o con dataArchiviazione passata).

NON gestisce:
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

from datetime import date

from filtering import estrai_scadenza, parse_data
from pdf_utils import estrai_scadenza_da_zip_url

_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

MAX_ALLEGATI_PER_PAGINA = 6
MAX_BYTES = 20 * 1024 * 1024

# Domini che il resolver generico non può gestire
_DOMINI_NON_RISOLVIBILI = ('trasparenzascuole.it',)

_ARGO_API = "https://www.portaleargo.it/albopretorio/api/public"
_ARGO_HEADERS = {
    'Content-Type': 'application/json',
    'Accept': 'application/json, text/plain, */*',
    'app_name': 'isa',
    'Origin': 'https://www.portaleargo.it',
    'Referer': 'https://www.portaleargo.it/albopretorio/online/',
    'User-Agent': _HEADERS['User-Agent'],
}
# Cache del listing albo per customerCode (una chiamata per scuola per run)
_argo_listing_cache: Dict[str, Optional[list]] = {}

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


def _parse_argo_link(url: str) -> Optional[tuple]:
    """Estrae (customerCode, attoId) da un deep-link Argo dettaglio-atto, o None."""
    m_code = re.search(r'customerCode=(S[CE]\d+)', url)
    m_id = re.search(r'[?&]id=(\d+)', url)
    if m_code and m_id:
        return m_code.group(1), m_id.group(1)
    return None


def _argo_listing(customer_code: str) -> Optional[list]:
    """Listing corrente dell'albo Argo per la scuola (cache per run). None su errore."""
    if customer_code in _argo_listing_cache:
        return _argo_listing_cache[customer_code]
    try:
        body = {
            "object": {"pubblicazioneDal": None, "pubblicazioneAl": None,
                       "archiviazioneDal": None, "archiviazioneAl": None,
                       "descrizione": None, "tipologiaAtto": None, "categoria": None},
            "page": 0, "size": 100,
            "sortBy": "dataPubblicazione,numRegistro", "sortDesc": True,
        }
        resp = requests.post(f"{_ARGO_API}/atti/filters/{customer_code}",
                             json=body, headers=_ARGO_HEADERS, timeout=30)
        resp.raise_for_status()
        listing = resp.json().get('list', [])
    except Exception:
        listing = None
    _argo_listing_cache[customer_code] = listing
    return listing


def _risolvi_argo(url: str) -> str:
    """Scadenza da un deep-link Argo: API allegati → ZIP pre-firmato → PDF."""
    parsed = _parse_argo_link(url)
    if not parsed:
        return ''
    _, atto_id = parsed
    try:
        resp = requests.get(f"{_ARGO_API}/atti/{atto_id}/allegati",
                            headers=_ARGO_HEADERS, timeout=15)
        resp.raise_for_status()
        zip_url = resp.text.strip().strip('"')
        if not zip_url:
            return ''
        return estrai_scadenza_da_zip_url(zip_url)
    except Exception:
        return ''


def argo_archiviato(url: str, oggi: Optional[date] = None) -> bool:
    """True se l'atto Argo non è più in pubblicazione: sparito dal listing corrente
    dell'albo oppure con dataArchiviazione passata. False su errore o link non-Argo
    (nel dubbio non si scarta)."""
    parsed = _parse_argo_link(url)
    if not parsed:
        return False
    customer_code, atto_id = parsed
    listing = _argo_listing(customer_code)
    if listing is None:
        return False
    atto = next((a for a in listing if str(a.get('id')) == atto_id), None)
    if atto is None:
        return True  # non più nell'albo → archiviato
    arch = parse_data(atto.get('dataArchiviazione') or '')
    return bool(arch and arch < (oggi or date.today()))


def _risolvi(url: str) -> str:
    low = url.lower()
    if any(d in low for d in _DOMINI_NON_RISOLVIBILI):
        return ''
    if 'portaleargo.it' in low:
        return _risolvi_argo(url)

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
