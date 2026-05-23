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

TRASPARENZA_BASE = "https://www.trasparenzascuole.it"
TRASPARENZA_PUBLIC = f"{TRASPARENZA_BASE}/Public/APDPublic_ExtV2.aspx"
TRASPARENZA_AJAX = f"{TRASPARENZA_BASE}/Ajax/APP_Ajax_Get.aspx"
SCUOLE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scuole_bat.json')
SLEEP_TRA_SCUOLE = 1.5
MAX_PAGINE = 20

_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'it-IT,it;q=0.9,en;q=0.8',
}
_AJAX_HEADERS = {
    **_HEADERS,
    'Content-Type': 'application/json; charset=UTF-8',
    'X-Requested-With': 'XMLHttpRequest',
}
_BASE_PAYLOAD = {
    'statopubblicazione': '0',  # solo atti in corso di pubblicazione
    'idtipoatto': '',
    'annoselezionato': '',
    'numeroprogressivo': '',
    'numeroprotocollo': '',
    'oggetto': '',
    'dataInizio': '',
    'dataFine': '',
    'searchfield': '',
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

        # Step 1: GET pagina → cust_id (GUID della scuola sul bottone Cerca)
        resp = session.get(page_url, headers=_HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        btn = soup.find('button', {'data-action': 'GET_APD_TABLE'})
        if not btn:
            return []
        cust_id = btn.get('data-cust-id', '')
        if not cust_id:
            return []

        # Step 2: GET INIT_APD — necessario per inizializzare la sessione lato server;
        # senza questo passo la POST GET_APD_TABLE restituisce sempre "Nessuno atto trovato"
        init_url = f"{TRASPARENZA_AJAX}?action=INIT_APD&Others={cust_id}&_={int(time.time() * 1000)}"
        session.get(init_url, headers={**_AJAX_HEADERS, 'Referer': page_url}, timeout=15)

        ajax_url = f"{TRASPARENZA_AJAX}?action=GET_APD_TABLE&Others={cust_id}"
        req_headers = {**_AJAX_HEADERS, 'Referer': page_url}

        risultati: List[Dict] = []
        for page_num in range(1, MAX_PAGINE + 1):
            payload = dict(_BASE_PAYLOAD)
            if page_num > 1:
                payload['PageNumber'] = str(page_num)

            try:
                r = session.post(ajax_url, data=json.dumps(payload), headers=req_headers, timeout=30)
                r.raise_for_status()
            except Exception:
                break

            if 'Nessuno atto trovato' in r.text:
                break

            soup_page = BeautifulSoup(r.text, 'html.parser')
            risultati.extend(self._parse_risposta(soup_page, cf, nome_scuola, page_url))

            m = re.search(r'Totale pagine (\d+) di (\d+)', r.text)
            if not m or page_num >= int(m.group(2)):
                break

            time.sleep(0.3)

        return risultati

    def _parse_risposta(self, soup: BeautifulSoup, cf: str, nome_scuola: str, page_url: str) -> List[Dict]:
        risultati = []
        for row in soup.find_all('tr'):
            cells = row.find_all('td')
            if len(cells) < 4:
                continue

            # L'oggetto vero dell'atto è nell'<i> tag della seconda colonna
            i_tag = row.find('i')
            oggetto_raw = i_tag.get_text(strip=True) if i_tag else ''
            oggetto = re.sub(r'^Oggetto:\s*', '', oggetto_raw).strip()
            testo = row.get_text(separator=' ', strip=True)

            if not is_sostegno_primaria_infanzia(oggetto or testo):
                continue

            scadenza = self._estrai_scadenza_da_riga(cells, oggetto)

            # data-idatto (GUID) come base dello stable_id — più stabile del testo
            btn_atto: Optional[BeautifulSoup] = row.find('button', {'data-action': 'GET_APD_ATTO'})
            id_atto = btn_atto.get('data-idatto', '') if btn_atto else ''
            sid_base = f"trasparenzascuole-{cf}-{id_atto}" if id_atto else testo

            risultati.append({
                'testo': testo,
                'title': f"[{nome_scuola}] {(oggetto or testo)[:100]}",
                'link': page_url,
                'tipo': identifica_tipo_interpello(oggetto or testo),
                'scadenza': scadenza,
                'source': self.name,
                'stable_id': compute_stable_id(sid_base),
                'data_rilevamento': datetime.now().isoformat(),
            })

        return risultati

    @staticmethod
    def _estrai_scadenza_da_riga(cells: list, oggetto: str) -> str:
        # Prima prova: oggetto dell'atto (se cita "entro il gg/mm/aaaa")
        scadenza = estrai_scadenza(oggetto)
        if scadenza:
            return scadenza
        # Seconda prova: seconda data nella colonna date (data archiviazione albo)
        if len(cells) >= 3:
            date_col = cells[2].get_text(separator='|', strip=True)
            dates = re.findall(r'\d{2}/\d{2}/\d{4}', date_col)
            if len(dates) >= 2:
                return dates[1]
        return ''
