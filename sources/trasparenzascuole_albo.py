import json
import os
import re
import time
from datetime import datetime
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from .base import BaseSource
from filtering import (
    compute_stable_id,
    estrai_scadenza,
    identifica_tipo_interpello,
    is_sostegno_primaria_infanzia,
)
from pdf_utils import estrai_scadenza_da_pdf

TRASPARENZA_BASE = "https://www.trasparenzascuole.it"
TRASPARENZA_PUBLIC = f"{TRASPARENZA_BASE}/Public/APDPublic_ExtV2.aspx"
TRASPARENZA_AJAX = f"{TRASPARENZA_BASE}/Ajax/APP_Ajax_Get.aspx"
SCUOLE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scuole_bat.json')
SLEEP_TRA_SCUOLE = 1.5
MAX_PAGINE = 20  # sicurezza: non iterare all'infinito

_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'it-IT,it;q=0.9,en;q=0.8',
}
_AJAX_HEADERS = {
    **_HEADERS,
    'Content-Type': 'application/json; charset=utf-8',
    'X-Requested-With': 'XMLHttpRequest',
}


class TrasparenzascuoleAlboSource(BaseSource):
    name = "trasparenzascuole_albo"

    def fetch(self) -> List[Dict]:
        try:
            scuole = self._carica_scuole()
            interpelli = []
            for scuola in scuole:
                if scuola.get('piattaforma') != 'trasparenzascuole':
                    continue
                cf = (scuola.get('params') or {}).get('codiceFiscale')
                if not cf:
                    continue
                nome = scuola.get('nome', cf)
                try:
                    trovati = self._fetch_scuola(cf, nome)
                    interpelli.extend(trovati)
                except Exception as e:
                    print(f"[{self.name}] Errore per CF {cf} ({nome}): {e}")
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

    def _fetch_scuola(self, cf: str, nome_scuola: str) -> List[Dict]:
        page_url = f"{TRASPARENZA_PUBLIC}?CF={cf}"
        session = requests.Session()

        # GET iniziale: ottieni il GUID della scuola (data-cust-id sul bottone Cerca)
        resp = session.get(page_url, headers=_HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')

        btn = soup.find('button', {'data-action': 'GET_APD_TABLE'})
        if not btn:
            return []
        cust_id = btn.get('data-cust-id', '')
        if not cust_id:
            return []

        ajax_url = f"{TRASPARENZA_AJAX}?action=GET_APD_TABLE&Others={cust_id}"
        referer_headers = {**_AJAX_HEADERS, 'Referer': page_url}

        base_payload = {
            'statopubblicazione': '0',  # 0 = In corso di pubblicazione
            'idtipoatto': '',
            'annoselezionato': '',
            'numeroprogressivo': '',
            'numeroprotocollo': '',
            'oggetto': '',
            'dataInizio': '',
            'dataFine': '',
            'searchfield': '',
        }

        risultati: List[Dict] = []
        for page_num in range(1, MAX_PAGINE + 1):
            payload = {**base_payload, 'PageNumber': str(page_num)}
            try:
                r = session.post(ajax_url, data=json.dumps(payload), headers=referer_headers, timeout=30)
                r.raise_for_status()
            except Exception:
                break

            soup_page = BeautifulSoup(r.text, 'html.parser')
            page_results = self._parse_tabella(soup_page, cf, nome_scuola)
            risultati.extend(page_results)

            # Calcola il numero totale di pagine dalla prima risposta
            if page_num == 1:
                total_pages = self._estrai_totale_pagine(soup_page)
                if total_pages <= 1:
                    break
            elif page_num >= total_pages:
                break

            time.sleep(0.5)

        return risultati

    def _estrai_totale_pagine(self, soup: BeautifulSoup) -> int:
        """Legge 'Totale pagine X di N' per sapere quante pagine ci sono."""
        testo = soup.get_text()
        m = re.search(r'Totale pagine\s+\d+\s+di\s+(\d+)', testo)
        if m:
            return int(m.group(1))
        # Fallback: prendi il data-page più alto tra i bottoni di paginazione
        max_page = 1
        for btn in soup.find_all(attrs={'data-page': True}):
            try:
                max_page = max(max_page, int(btn['data-page']))
            except (ValueError, TypeError):
                pass
        return max_page

    def _parse_tabella(self, soup: BeautifulSoup, cf: str, nome_scuola: str) -> List[Dict]:
        risultati = []

        # La tabella non ha header row: tutte le <tr> sono dati
        table = (
            soup.find('table', id=re.compile(r'grid|result|atti|albo', re.I))
            or soup.find('table', class_=re.compile(r'grid|result|atti|albo', re.I))
            or next((t for t in soup.find_all('table') if t.find('td')), None)
        )
        if not table:
            return risultati

        for row in table.find_all('tr'):
            cells = row.find_all('td')
            if len(cells) < 2:
                continue

            testo = row.get_text(separator=' ', strip=True)
            if not is_sostegno_primaria_infanzia(testo):
                continue

            link_tag = row.find('a', href=True)
            link: Optional[str] = None
            if link_tag:
                href = link_tag['href']
                if href.startswith('http'):
                    link = href
                elif href.startswith('/'):
                    link = TRASPARENZA_BASE + href

            doc_id = self._estrai_id_atto(link) if link else None
            sid_base = f"trasparenzascuole-{cf}-{doc_id}" if doc_id else testo

            scadenza = estrai_scadenza(testo)
            if not scadenza and link and link.lower().endswith('.pdf'):
                scadenza = estrai_scadenza_da_pdf(link)

            oggetto = next((c.get_text(strip=True) for c in cells if c.get_text(strip=True)), testo[:120])

            risultati.append({
                'testo': testo,
                'title': f"[{nome_scuola}] {oggetto[:100]}",
                'link': link,
                'tipo': identifica_tipo_interpello(testo),
                'scadenza': scadenza,
                'source': self.name,
                'stable_id': compute_stable_id(sid_base),
                'data_rilevamento': datetime.now().isoformat(),
            })

        return risultati

    @staticmethod
    def _estrai_id_atto(link: str) -> Optional[str]:
        m = re.search(r'[?&][iI][dD]=(\d+)', link)
        if m:
            return m.group(1)
        m = re.search(r'/(\d{4,})(?:/|$|\?)', link)
        return m.group(1) if m else None
