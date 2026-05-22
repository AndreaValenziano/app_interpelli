import json
import os
import time
from datetime import datetime
from typing import Dict, List, Optional

from .base import BaseSource
from filtering import (
    compute_stable_id,
    estrai_scadenza,
    identifica_tipo_interpello,
    is_sostegno_primaria_infanzia,
)

ARGO_API_BASE = "https://www.portaleargo.it/albopretorio/api/public"

ARGO_HEADERS = {
    'Content-Type': 'application/json',
    'Accept': 'application/json, text/plain, */*',
    'app_name': 'isa',
    'Origin': 'https://www.portaleargo.it',
    'Referer': 'https://www.portaleargo.it/albopretorio/online/',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36',
}

PAGE_SIZE = 100
SLEEP_TRA_SCUOLE = 1.0

SCUOLE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scuole_bat.json')


class ArgoAlboSource(BaseSource):
    name = "argo_albo"

    def fetch(self) -> List[Dict]:
        try:
            scuole = self._carica_scuole()
            if not scuole:
                return []
            interpelli = []
            for scuola in scuole:
                codice = scuola.get('customerCode')
                if not codice:
                    continue
                try:
                    trovati = self._fetch_scuola(scuola)
                    interpelli.extend(trovati)
                except Exception as e:
                    print(f"[{self.name}] Errore per {codice} ({scuola.get('nome', '?')}): {e}")
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

    def _fetch_scuola(self, scuola: Dict) -> List[Dict]:
        codice = scuola['customerCode']
        nome = scuola.get('nome', codice)
        url = f"{ARGO_API_BASE}/atti/filters/{codice}"

        body = {
            "object": {
                "pubblicazioneDal": None, "pubblicazioneAl": None,
                "archiviazioneDal": None, "archiviazioneAl": None,
                "descrizione": None, "tipologiaAtto": None, "categoria": None,
            },
            "page": 0,
            "size": PAGE_SIZE,
            "sortBy": "dataPubblicazione,numRegistro",
            "sortDesc": True,
        }

        resp = self._http_post(url, json=body, extra_headers=ARGO_HEADERS)
        data = resp.json()

        risultati = []
        for atto in data.get('list', []):
            entry = self._process_atto(atto, codice, nome)
            if entry:
                risultati.append(entry)
        return risultati

    def _process_atto(self, atto: Dict, customer_code: str, nome_scuola: str) -> Optional[Dict]:
        categoria_desc = (atto.get('categoria') or {}).get('desc', '')
        if 'interpell' not in categoria_desc.lower():
            return None

        descrizione = atto.get('descrizione', '')
        if 'graduatoria' in descrizione.lower():
            return None

        # I codici (ADEE/EEEE/…) spesso sono solo nel nome del PDF allegato
        nomi_allegati = ' '.join(a.get('nome', '') for a in atto.get('allegati', []))
        testo = f"{descrizione} {nomi_allegati}".strip()

        if not is_sostegno_primaria_infanzia(testo):
            return None

        scadenza = estrai_scadenza(testo) or self._formatta_data(atto.get('dataArchiviazione'))

        atto_id = atto.get('id')
        link = f"https://www.portaleargo.it/albopretorio/online/#/?customerCode={customer_code}"

        return {
            'testo': testo,
            'title': f"[{nome_scuola}] {descrizione[:100]}",
            'link': link,
            'tipo': identifica_tipo_interpello(testo),
            'scadenza': scadenza,
            'source': self.name,
            'stable_id': compute_stable_id(f"argo-{customer_code}-{atto_id}"),
            'data_rilevamento': datetime.now().isoformat(),
        }

    @staticmethod
    def _formatta_data(data_str: str) -> str:
        if not data_str:
            return ''
        try:
            d = datetime.strptime(data_str[:10], '%Y-%m-%d')
            return d.strftime('%d/%m/%Y')
        except ValueError:
            return ''
