import json
import os
import re
import time
from datetime import datetime
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from .base import BaseSource
from filtering import (
    compute_stable_id,
    estrai_scadenza,
    identifica_tipo_interpello,
    is_likely_interpello,
    is_sostegno_primaria_infanzia,
)

NUVOLA_BASE = "https://nuvola.madisoft.it/bacheca-digitale/bacheca"
SCUOLE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scuole_bat.json')
SLEEP_TRA_SCUOLE = 1.0


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
                    print(f"[{self.name}] Errore per {cod_miur} ({nome}): {e}")
                time.sleep(SLEEP_TRA_SCUOLE)
            return interpelli
        except Exception as e:
            print(f"[{self.name}] Errore: {e}")
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

    def _parse_tabella(self, soup: BeautifulSoup, cod_miur: str, nome_scuola: str) -> List[Dict]:
        risultati = []
        table = soup.find('table')
        if not table:
            return risultati

        rows = table.find_all('tr')
        for row in rows[1:]:  # salta header
            cells = row.find_all('td')
            if not cells:
                continue

            testo = row.get_text(separator=' ', strip=True)
            if not is_sostegno_primaria_infanzia(testo):
                if self._reporter and is_likely_interpello(testo):
                    oggetto_rej = cells[1].get_text(strip=True) if len(cells) > 1 else testo[:120]
                    link_tag_rej = row.find('a', href=True)
                    self._reporter.record_rejected({
                        'testo': testo,
                        'title': f"[{nome_scuola}] {oggetto_rej[:100]}",
                        'link': link_tag_rej['href'] if link_tag_rej else None,
                        'tipo': '', 'scadenza': '', 'source': self.name,
                        'stable_id': '', 'data_rilevamento': datetime.now().isoformat(),
                    }, 'codici_non_target', self.name)
                continue

            link_tag = row.find('a', href=True)
            link = link_tag['href'] if link_tag else None

            doc_id = self._estrai_doc_id(link) if link else None
            sid_base = f"nuvola-{cod_miur}-{doc_id}" if doc_id else testo

            # Oggetto tipicamente in 2a colonna
            oggetto = cells[1].get_text(strip=True) if len(cells) > 1 else testo[:120]

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
