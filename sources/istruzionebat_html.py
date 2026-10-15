from bs4 import BeautifulSoup
from datetime import date, datetime
from typing import List, Dict, Optional

from .base import BaseSource
from filtering import (
    is_sostegno_primaria_infanzia,
    identifica_tipo_interpello,
    estrai_scadenza,
    compute_stable_id,
)

URL_BASE = "https://www.istruzionebat.it/interpelli/a-s-{inizio}-{fine}/"

# Tag che contengono le voci: nella pagina 2026-27 sono <h2>/<h3>, negli anni
# precedenti <li>/<p>/<h4>
TAG_VOCI = ['h2', 'h3', 'h4', 'li', 'p']


def url_anno_scolastico(oggi: Optional[date] = None) -> str:
    """URL dell'indice interpelli dell'anno scolastico in corso (da settembre)."""
    oggi = oggi or date.today()
    inizio = oggi.year if oggi.month >= 9 else oggi.year - 1
    return URL_BASE.format(inizio=inizio, fine=inizio + 1)


def _url_anno_precedente(url: str) -> str:
    inizio = int(url.rstrip('/').split('-')[-2])
    return URL_BASE.format(inizio=inizio - 1, fine=inizio)


class IstruzioneBatHtmlSource(BaseSource):
    name = "istruzionebat_html"

    def fetch(self, reporter=None) -> List[Dict]:
        self._reporter = reporter
        try:
            url = url_anno_scolastico()
            try:
                response = self._http_get(url)
            except Exception:
                # A inizio anno scolastico la pagina nuova può non esistere ancora
                url = _url_anno_precedente(url)
                response = self._http_get(url)
            soup = BeautifulSoup(response.text, 'html.parser')
            contenuto = (soup.find('div', class_='testolungo')
                         or soup.find('div', class_='entry-content')
                         or soup.find('article'))
            voci = [el for el in contenuto.find_all(TAG_VOCI)
                    if el.get_text(strip=True)] if contenuto else []
            if not voci:
                self.segnala_errore(f"Nessuna voce trovata in {url}: struttura della pagina cambiata?")
                return []
            return [ip for ip in (self._process_voce(el) for el in voci) if ip]
        except Exception as e:
            self.segnala_errore(f"Errore: {e}")
            return []

    def _process_voce(self, elemento) -> Optional[Dict]:
        testo = elemento.get_text(separator=' ', strip=True)
        link_tag = elemento.find('a')
        link = link_tag['href'] if link_tag and link_tag.get('href') else None
        if not is_sostegno_primaria_infanzia(testo):
            if self._reporter:
                self._reporter.record_rejected({
                    'testo': testo, 'title': testo[:120],
                    'link': link, 'tipo': '',
                    'scadenza': '', 'source': self.name,
                    'stable_id': '', 'data_rilevamento': datetime.now().isoformat(),
                }, 'codici_non_target', self.name)
            return None
        return {
            'testo': testo,
            'title': testo.lstrip('-–— ')[:120],
            'link': link,
            'tipo': identifica_tipo_interpello(testo),
            'scadenza': estrai_scadenza(testo),
            'source': self.name,
            'stable_id': compute_stable_id(testo),
            'data_rilevamento': datetime.now().isoformat(),
        }
