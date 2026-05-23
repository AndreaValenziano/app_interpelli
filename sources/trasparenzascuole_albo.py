import json
import os
import random
import re
import time
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional

from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests
from curl_cffi.requests.errors import RequestsError

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

# curl_cffi con impersonate="chrome131" gestisce automaticamente UA, Accept, Sec-Fetch-*, sec-ch-ua*.
# Teniamo solo gli header XHR che il sito verifica e che l'impersonation non può inferire.
_AJAX_EXTRA = {
    'Content-Type': 'application/json; charset=UTF-8',
    'X-Requested-With': 'XMLHttpRequest',
    'Origin': TRASPARENZA_BASE,
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

_RETRY_STATUSES = {403, 429, 500, 502, 503, 504}


class TrasparenzascuoleAlboSource(BaseSource):
    name = "trasparenzascuole_albo"

    def fetch(self) -> List[Dict]:
        try:
            scuole = self._carica_scuole()
            interpelli = []
            errors_by_status: dict = defaultdict(list)  # status_code → [nome, ...]
            session = self._make_session()

            for scuola in scuole:
                if scuola.get('piattaforma') != 'trasparenzascuole':
                    continue
                cf = (scuola.get('params') or {}).get('codiceFiscale')
                if not cf:
                    continue
                nome = scuola.get('nome', cf)
                try:
                    trovati = self._fetch_scuola(session, cf, nome)
                    interpelli.extend(trovati)
                except RequestsError as e:
                    status = getattr(getattr(e, 'response', None), 'status_code', 0) or 0
                    if not errors_by_status[status]:
                        print(f"[{self.name}] Errore per CF {cf} ({nome}): {e}")
                    errors_by_status[status].append(nome)
                except Exception as e:
                    print(f"[{self.name}] Errore per CF {cf} ({nome}): {e}")
                time.sleep(SLEEP_TRA_SCUOLE + random.uniform(0, 0.8))

            for status, nomi in errors_by_status.items():
                if len(nomi) > 1:
                    label = "Bloccato da WAF Cloudflare" if status == 403 else f"HTTP {status}"
                    print(f"[{self.name}] ⚠  {label} su {len(nomi)} scuole (probabile block IP su runner CI)")
            return interpelli
        except Exception as e:
            print(f"[{self.name}] Errore: {e}")
            return []

    @staticmethod
    def _make_session() -> cffi_requests.Session:
        session = cffi_requests.Session(impersonate="chrome131")
        try:
            session.get(TRASPARENZA_BASE + '/', timeout=15)
        except Exception:
            pass  # warm-up fallito: si prosegue comunque
        return session

    def _carica_scuole(self) -> List[Dict]:
        if not os.path.exists(SCUOLE_FILE):
            return []
        with open(SCUOLE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _request_with_retry(
        self,
        session: cffi_requests.Session,
        method: str,
        url: str,
        *,
        headers: Optional[dict] = None,
        data: Optional[str] = None,
        timeout: int = 30,
        max_retries: int = 3,
    ):
        for attempt in range(max_retries + 1):
            try:
                r = session.request(method, url, headers=headers, data=data, timeout=timeout)
            except RequestsError:
                if attempt >= max_retries:
                    raise
                time.sleep(2 * (2 ** attempt))  # 2s, 4s, 8s
                continue
            if r.status_code in _RETRY_STATUSES and attempt < max_retries:
                time.sleep(2 * (2 ** attempt))
                continue
            r.raise_for_status()
            return r

    def _fetch_scuola(self, session: cffi_requests.Session, cf: str, nome_scuola: str) -> List[Dict]:
        page_url = f"{TRASPARENZA_PUBLIC}?CF={cf}"

        # Step 1: GET pagina → cust_id (GUID della scuola sul bottone Cerca)
        resp = self._request_with_retry(session, 'GET', page_url, timeout=30)
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
        try:
            session.get(init_url, headers={'Referer': page_url}, timeout=15)
        except Exception:
            pass

        ajax_url = f"{TRASPARENZA_AJAX}?action=GET_APD_TABLE&Others={cust_id}"
        req_headers = {**_AJAX_EXTRA, 'Referer': page_url}

        risultati: List[Dict] = []
        for page_num in range(1, MAX_PAGINE + 1):
            payload = dict(_BASE_PAYLOAD)
            if page_num > 1:
                payload['PageNumber'] = str(page_num)

            try:
                r = self._request_with_retry(
                    session, 'POST', ajax_url,
                    data=json.dumps(payload),
                    headers=req_headers,
                    timeout=30,
                )
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
    def _estrai_scadenza_da_riga(_cells: list, oggetto: str) -> str:
        return estrai_scadenza(oggetto)
