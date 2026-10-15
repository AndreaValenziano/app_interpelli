import json
import os
import re
import time
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import BaseSource
from filtering import (
    compute_stable_id,
    estrai_scadenza,
    identifica_tipo_interpello,
    is_likely_interpello,
    is_sostegno_primaria_infanzia,
    normalizza_data,
    parse_data,
)

NUVOLA_BASE = "https://nuvola.madisoft.it/bacheca-digitale/bacheca"
SCUOLE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scuole_bat.json')
SLEEP_TRA_SCUOLE = 1.0
# La bacheca tiene 'in pubblicazione' anche interpelli di mesi/anni prima: oltre
# questa età dalla pubblicazione sono certamente chiusi
MAX_GIORNI_PUBBLICAZIONE = 30


class NuvolaAlboSource(BaseSource):
    name = "nuvola_albo"

    def fetch(self, reporter=None) -> List[Dict]:
        self._reporter = reporter
        try:
            scuole = self._carica_scuole()
            interpelli = []
            for scuola in scuole:
                if scuola.get('piattaforma') != 'nuvola':
                    continue
                cod_miur = (scuola.get('params') or {}).get('codMiur')
                if not cod_miur:
                    continue
                nome = scuola.get('nome', cod_miur)
                try:
                    trovati = self._fetch_scuola(cod_miur, nome)
                    interpelli.extend(trovati)
                except Exception as e:
                    self.segnala_errore(f"Errore per {cod_miur} ({nome}): {e}")
                time.sleep(SLEEP_TRA_SCUOLE)
            return interpelli
        except Exception as e:
            self.segnala_errore(f"Errore: {e}")
            return []

    def _carica_scuole(self) -> List[Dict]:
        if not os.path.exists(SCUOLE_FILE):
            return []
        with open(SCUOLE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _fetch_scuola(self, cod_miur: str, nome_scuola: str) -> List[Dict]:
        # Prova prima la categoria 5 (albo/avvisi), poi altre tipologie comuni.
        # La pagina radice /bacheca-digitale/bacheca/{cod} espone i link alle categorie disponibili.
        radice = f"{NUVOLA_BASE}/{cod_miur}"
        tipologie = self._scopri_tipologie(radice) or [5, 1, 2, 3, 4]

        risultati = []
        for tipologia in tipologie:
            url = f"{radice}/{tipologia}/IN_PUBBLICAZIONE/0/show"
            try:
                resp = self._http_get(url)
                soup = BeautifulSoup(resp.text, 'html.parser')
                risultati.extend(self._parse_tabella(soup, cod_miur, nome_scuola))
            except Exception:
                continue
        return risultati

    def _scopri_tipologie(self, radice_url: str) -> List[int]:
        """Legge la pagina radice e raccoglie i numeri di tipologia dai link interni."""
        try:
            resp = self._http_get(radice_url)
            soup = BeautifulSoup(resp.text, 'html.parser')
            trovate = []
            for a in soup.find_all('a', href=True):
                m = re.search(r'/bacheca/[^/]+/(\d+)/IN_PUBBLICAZIONE', a['href'])
                if m:
                    val = int(m.group(1))
                    if val not in trovate:
                        trovate.append(val)
            return trovate
        except Exception:
            return []

    def _parse_tabella(self, soup: BeautifulSoup, cod_miur: str, nome_scuola: str,
                       oggi: Optional[date] = None) -> List[Dict]:
        risultati = []
        table = soup.find('table')
        if not table:
            return risultati

        # Le colonne cambiano tra scuole e tipologie ('Oggetto' 2a o 3a colonna):
        # si leggono dall'intestazione <th>, se c'è
        idx_oggetto, idx_pubblicazione = 1, None
        intestazione = table.find('tr')
        if intestazione and intestazione.find('th'):
            nomi = [th.get_text(' ', strip=True).lower() for th in intestazione.find_all('th')]
            idx_oggetto = next((i for i, n in enumerate(nomi) if n == 'oggetto'), 1)
            idx_pubblicazione = next((i for i, n in enumerate(nomi)
                                      if n.startswith('data pubblicazione')), None)
        limite = (oggi or date.today()) - timedelta(days=MAX_GIORNI_PUBBLICAZIONE)

        for row in table.find_all('tr'):
            cells = row.find_all('td')
            # Righe senza <td> (intestazione) o senza link al documento (riga dei filtri)
            link_tag = row.find('a', href=re.compile(r'/bacheca-digitale/\d+/documento/'))
            if not cells or not link_tag:
                continue

            testo = row.get_text(separator=' ', strip=True)
            oggetto = (cells[idx_oggetto].get_text(' ', strip=True)
                       if len(cells) > idx_oggetto else '') or testo[:120]
            link = urljoin('https://nuvola.madisoft.it/', link_tag['href'])

            if idx_pubblicazione is not None and len(cells) > idx_pubblicazione:
                pubblicato = parse_data(normalizza_data(cells[idx_pubblicazione].get_text(strip=True)))
                if pubblicato and pubblicato < limite:
                    continue

            if not is_sostegno_primaria_infanzia(testo):
                if self._reporter and is_likely_interpello(testo):
                    self._reporter.record_rejected({
                        'testo': testo,
                        'title': f"[{nome_scuola}] {oggetto[:100]}",
                        'link': link,
                        'tipo': '', 'scadenza': '', 'source': self.name,
                        'stable_id': '', 'data_rilevamento': datetime.now().isoformat(),
                    }, 'codici_non_target', self.name)
                continue

            doc_id = self._estrai_doc_id(link)
            sid_base = f"nuvola-{cod_miur}-{doc_id}" if doc_id else testo

            risultati.append({
                'testo': testo,
                'title': f"[{nome_scuola}] {oggetto[:100]}",
                'link': link,
                'tipo': identifica_tipo_interpello(testo),
                'scadenza': estrai_scadenza(testo),
                'source': self.name,
                'stable_id': compute_stable_id(sid_base),
                'data_rilevamento': datetime.now().isoformat(),
            })

        return risultati

    @staticmethod
    def _estrai_doc_id(link: str) -> Optional[str]:
        # Pattern: /bacheca-digitale/{id}/documento/{codMiur}
        m = re.search(r'/bacheca-digitale/(\d+)/documento/', link)
        return m.group(1) if m else None
