import feedparser
from bs4 import BeautifulSoup
from datetime import datetime
from typing import List, Dict

from .base import BaseSource
from filtering import (
    is_sostegno_primaria_infanzia,
    identifica_tipo_interpello,
    estrai_scadenza,
    compute_stable_id,
)
FEED_URL = "https://www.scuolainterpelli.it/feed/"

# Match case-insensitive — aggiornare se il feed usa un'etichetta diversa per la provincia BAT
BAT_PROVINCE_KEYWORDS = {
    'BARLETTA', 'ANDRIA', 'TRANI', 'BAT', 'BT',
    'BARLETTA-ANDRIA-TRANI', 'BARLETTA ANDRIA TRANI',
}


class ScuolaInterppelliRssSource(BaseSource):
    name = "scuolainterpelli_rss"

    def fetch(self, reporter=None) -> List[Dict]:
        self._reporter = reporter
        try:
            feed = feedparser.parse(FEED_URL)
            interpelli = []
            for entry in feed.entries:
                html_content = ''
                if hasattr(entry, 'content') and entry.content:
                    html_content = entry.content[0].get('value', '')
                if not html_content:
                    html_content = entry.get('summary', '')
                if not html_content:
                    continue
                interpelli.extend(self._parse_html(html_content))
            return interpelli
        except Exception as e:
            print(f"[{self.name}] Errore: {e}")
            return []

    def _parse_html(self, html: str) -> List[Dict]:
        soup = BeautifulSoup(html, 'html.parser')

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
                in_bat = any(p in node_text_upper for p in BAT_PROVINCE_KEYWORDS)
                continue

            if not in_bat:
                continue

            # Elabora gli elementi come voci di interpello
            if node.name in ('ul', 'ol'):
                for li in node.find_all('li'):
                    self._process_entry(li, results)
            else:
                self._process_entry(node, results)

        return results

    def _process_entry(self, element, results: List[Dict]) -> None:
        testo = element.get_text(separator=' ', strip=True)
        if not testo:
            return
        if not is_sostegno_primaria_infanzia(testo):
            if self._reporter:
                link_tag = element.find('a')
                link = link_tag.get('href') if link_tag else None
                title = link_tag.get_text(strip=True) if link_tag else testo[:120]
                self._reporter.record_rejected({
                    'testo': testo, 'title': title,
                    'link': link, 'tipo': '',
                    'scadenza': '', 'source': self.name,
                    'stable_id': '', 'data_rilevamento': datetime.now().isoformat(),
                }, 'codici_non_target', self.name)
            return
        link_tag = element.find('a')
        link = link_tag.get('href') if link_tag else None
        title = link_tag.get_text(strip=True) if link_tag else testo[:120]
        results.append({
            'testo': testo,
            'title': title,
            'link': link,
            'tipo': identifica_tipo_interpello(testo),
            'scadenza': estrai_scadenza(testo),
            'source': self.name,
            'stable_id': compute_stable_id(testo),
            'data_rilevamento': datetime.now().isoformat(),
        })
