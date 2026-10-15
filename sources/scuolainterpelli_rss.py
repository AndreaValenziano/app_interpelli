import re
from datetime import date, datetime, timedelta
from typing import List, Dict, Optional
from urllib.parse import urlparse

import feedparser
from bs4 import BeautifulSoup

from .base import BaseSource
from filtering import (
    is_sostegno_primaria_infanzia,
    identifica_tipo_interpello,
    estrai_scadenza,
    compute_stable_id,
    normalizza_data,
    parse_data,
    parse_link_argo,
)
FEED_URL = "https://www.scuolainterpelli.it/feed/"

# Aggiornare se il feed usa un'etichetta diversa per la provincia BAT. Confronto per
# parola intera: 'ALESSANDRIA' contiene 'ANDRIA'
BAT_PROVINCE_KEYWORDS = {
    'BARLETTA', 'ANDRIA', 'TRANI', 'BAT', 'BT',
    'BARLETTA-ANDRIA-TRANI', 'BARLETTA ANDRIA TRANI',
}
_BAT_RE = re.compile(r'\b(?:' + '|'.join(sorted(map(re.escape, BAT_PROVINCE_KEYWORDS), key=len,
                                               reverse=True)) + r')\b')

# Il feed conserva circa due settimane di numeri; gli interpelli scadono in 1-3 giorni
MAX_GIORNI = 3


class ScuolaInterppelliRssSource(BaseSource):
    name = "scuolainterpelli_rss"

    def fetch(self, reporter=None) -> List[Dict]:
        self._reporter = reporter
        try:
            feed = feedparser.parse(FEED_URL)
            interpelli = []
            puglia = False
            for entry in feed.entries:
                html_content = ''
                if hasattr(entry, 'content') and entry.content:
                    html_content = entry.content[0].get('value', '')
                if not html_content:
                    html_content = entry.get('summary', '')
                if not html_content:
                    continue
                puglia = puglia or 'PUGLIA' in html_content.upper()
                interpelli.extend(self._parse_html(html_content))
            if not feed.entries:
                self.segnala_errore(f"Feed vuoto o illeggibile: {feed.get('bozo_exception', '')}")
            elif not puglia:
                self.segnala_errore("Nessuna sezione PUGLIA nel feed: struttura cambiata?")
            return interpelli
        except Exception as e:
            self.segnala_errore(f"Errore: {e}")
            return []

    def _parse_html(self, html: str, oggi: Optional[date] = None) -> List[Dict]:
        soup = BeautifulSoup(html, 'html.parser')
        limite = (oggi or date.today()) - timedelta(days=MAX_GIORNI)

        # Trova l'h2 della regione PUGLIA
        puglia_h2 = None
        for h2 in soup.find_all('h2'):
            if 'PUGLIA' in h2.get_text().upper():
                puglia_h2 = h2
                break
        if not puglia_h2:
            return []

        results = []
        in_bat = False

        for node in puglia_h2.next_siblings:
            if not hasattr(node, 'name') or node.name is None:
                continue
            if node.name == 'h2':
                break  # prossima regione

            node_text_upper = node.get_text(separator=' ', strip=True).upper()

            # Rilevamento intestazione di provincia
            if 'PUBBLICATI DA' in node_text_upper:
                in_bat = bool(_BAT_RE.search(node_text_upper))
                continue

            if not in_bat:
                continue

            # Elabora gli elementi come voci di interpello; la data di pubblicazione
            # sta nel paragrafo <p><em>12 ottobre 2026</em></p> successivo alla voce
            if node.name in ('ul', 'ol'):
                for li in node.find_all('li'):
                    self._process_entry(li, '', limite, results)
            elif node.find('a'):
                self._process_entry(node, _data_paragrafo_successivo(node), limite, results)

        return results

    def _process_entry(self, element, data: str, limite: date, results: List[Dict]) -> None:
        testo = element.get_text(separator=' ', strip=True)
        if not testo:
            return
        pubblicato = parse_data(data)
        if pubblicato and pubblicato < limite:
            return  # numero vecchio del feed: interpello certamente chiuso
        link_tag = element.find('a')
        link = link_tag.get('href') if link_tag else None
        # Il testo della voce è solo 'EEEE – VISUALIZZA INTERPELLI': titolo da codici,
        # destinazione del link e data
        codici = re.split(r'\s*[–—-]\s*', testo)[0].strip() if link_tag else testo[:120]
        title = ' – '.join(x for x in (codici, _destinazione(link), data) if x)
        if data:
            testo = f"{testo} {data}"
        if not is_sostegno_primaria_infanzia(testo):
            if self._reporter:
                self._reporter.record_rejected({
                    'testo': testo, 'title': title,
                    'link': link, 'tipo': '',
                    'scadenza': '', 'source': self.name,
                    'stable_id': '', 'data_rilevamento': datetime.now().isoformat(),
                }, 'codici_non_target', self.name)
            return
        results.append({
            'testo': testo,
            'title': title,
            'link': link,
            'tipo': identifica_tipo_interpello(testo),
            'scadenza': estrai_scadenza(testo),
            'source': self.name,
            # Link + data (+ codici): lo stesso testo con lo stesso link generico
            # (homepage della scuola) si ripete per interpelli diversi
            'stable_id': compute_stable_id(f"scuolainterpelli {codici} {link or ''} {data}"),
            'data_rilevamento': datetime.now().isoformat(),
        })


def _data_paragrafo_successivo(node) -> str:
    """'DD/MM/YYYY' se il primo elemento dopo la voce è un paragrafo con la sola data."""
    succ = node.find_next_sibling()
    if succ is None or succ.find('a'):
        return ''
    testo = succ.get_text(' ', strip=True)
    return normalizza_data(testo) if len(testo) <= 30 else ''


def _destinazione(link: Optional[str]) -> str:
    """Descrizione breve della destinazione del link per il titolo."""
    if not link:
        return ''
    argo = parse_link_argo(link)
    if argo:
        return f"albo Argo {argo[0]} atto {argo[1]}"
    host = urlparse(link).netloc
    return host[4:] if host.startswith('www.') else host
