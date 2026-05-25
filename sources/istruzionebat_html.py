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
from pdf_utils import estrai_scadenza_da_pdf

# Aggiornare l'URL ogni anno scolastico
URL = "https://www.istruzionebat.it/interpelli/a-s-2025-2026/"


class IstruzioneBatHtmlSource(BaseSource):
    name = "istruzionebat_html"

    def fetch(self, reporter=None) -> List[Dict]:
        self._reporter = reporter
        try:
            response = self._http_get(URL)
            soup = BeautifulSoup(response.text, 'html.parser')
            contenuto = soup.find('div', class_='entry-content') or soup.find('article')
            if not contenuto:
                return []
            interpelli = []
            for elemento in contenuto.find_all(['li', 'p', 'h4']):
                testo = elemento.get_text(strip=True)
                if not testo:
                    continue
                if not is_sostegno_primaria_infanzia(testo):
                    if self._reporter:
                        link_tag = elemento.find('a')
                        link = link_tag['href'] if link_tag and link_tag.get('href') else None
                        self._reporter.record_rejected({
                            'testo': testo, 'title': testo[:120],
                            'link': link, 'tipo': '',
                            'scadenza': '', 'source': self.name,
                            'stable_id': '', 'data_rilevamento': datetime.now().isoformat(),
                        }, 'codici_non_target', self.name)
                    continue
                link_tag = elemento.find('a')
                link = link_tag['href'] if link_tag and link_tag.get('href') else None
                interpelli.append({
                    'testo': testo,
                    'title': testo[:120],
                    'link': link,
                    'tipo': identifica_tipo_interpello(testo),
                    'scadenza': estrai_scadenza(testo) or (estrai_scadenza_da_pdf(link) if link and link.lower().endswith('.pdf') else ''),
                    'source': self.name,
                    'stable_id': compute_stable_id(testo),
                    'data_rilevamento': datetime.now().isoformat(),
                })
            return interpelli
        except Exception as e:
            print(f"[{self.name}] Errore: {e}")
            return []
