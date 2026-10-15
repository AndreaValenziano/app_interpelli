import json
import os
import re
import time
from datetime import date, datetime
from typing import Dict, List, Optional

import requests

from .base import BaseSource
from filtering import (
    CODICI_OBIETTIVO,
    compute_stable_id,
    estrai_scadenza,
    identifica_tipo_interpello,
    is_esito_interpello,
    is_sostegno_primaria_infanzia,
    normalizza_codici,
    parse_data,
)
from pdf_utils import estrai_scadenza_da_zip_url, testo_da_zip_url

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

# Un qualunque codice classe di concorso nella descrizione (A022, AI56, BA02, ADMM,
# EEEE…): se c'è, i PDF non servono per capire se l'interpello è di nostro interesse
_CLASSE_RE = re.compile(r'\b(?:[AB][A-Z0-9]\d{2}|AD[A-Z]{2}|EEEE|AAAA)\b')

SCUOLE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scuole_bat.json')


class ArgoAlboSource(BaseSource):
    name = "argo_albo"

    def fetch(self, reporter=None) -> List[Dict]:
        self._reporter = reporter
        try:
            scuole = self._carica_scuole()
            if not scuole:
                return []
            interpelli = []
            for scuola in scuole:
                if scuola.get('piattaforma') != 'argo':
                    continue
                codice = (scuola.get('params') or {}).get('customerCode')
                if not codice:
                    continue
                try:
                    trovati = self._fetch_scuola(scuola)
                    interpelli.extend(trovati)
                except Exception as e:
                    self.segnala_errore(f"Errore per {codice} ({scuola.get('nome', '?')}): {e}")
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

    def _fetch_scuola(self, scuola: Dict) -> List[Dict]:
        codice = (scuola.get('params') or {}).get('customerCode', '')
        nome = scuola.get('nome', codice)
        data = lista_atti(codice, post=self._http_post)
        risultati = []
        for atto in data['list']:
            entry = self._process_atto(atto, codice, nome)
            if entry:
                risultati.append(entry)
        return risultati

    def _process_atto(self, atto: Dict, customer_code: str, nome_scuola: str) -> Optional[Dict]:
        # La categoria è testo libero diverso per ogni scuola ('BANDI DI GARA E
        # PROCEDURE DI RECLUTAMENTO', 'Bandi e Contratti', null…): si filtra sulla descrizione
        descrizione = (atto.get('descrizione') or '').strip()
        desc_norm = normalizza_codici(descrizione)
        candidato = ('interpell' in descrizione.lower()
                     or any(c in desc_norm.upper() for c in CODICI_OBIETTIVO))
        if not candidato or atto.get('annullato'):
            return None

        # Atto già archiviato (DD/MM/YYYY passata) → non più in pubblicazione
        arch = parse_data(data_archiviazione(atto))
        if arch and arch < date.today():
            return None

        atto_id = atto.get('id')
        link = f"https://www.portaleargo.it/albopretorio/online/#/{customer_code}/atti/{atto_id}"
        title = f"[{nome_scuola}] {descrizione[:100]}"
        testo = descrizione
        scadenza = ''

        # Il listing non riporta più i nomi degli allegati: se la descrizione non dice
        # la classe di concorso, il codice si cerca nei PDF dell'atto
        if not _CLASSE_RE.search(desc_norm.upper()) and not is_esito_interpello(descrizione):
            testo_allegati = normalizza_codici(testo_da_zip_url(self._url_zip_allegati(atto_id)))
            codici = [c for c in CODICI_OBIETTIVO if c in testo_allegati.upper()]
            if codici:
                testo = f"{descrizione} {' '.join(codici)}"
                scadenza = estrai_scadenza(testo_allegati)

        if 'graduatoria' in descrizione.lower() or not is_sostegno_primaria_infanzia(testo):
            if self._reporter:
                self._reporter.record_rejected({
                    'testo': testo, 'title': title, 'link': link,
                    'tipo': '', 'scadenza': '', 'source': self.name,
                    'stable_id': '', 'data_rilevamento': datetime.now().isoformat(),
                }, 'codici_non_target', self.name)
            return None

        scadenza = scadenza or estrai_scadenza(testo) or self._estrai_scadenza_da_allegati(atto_id)
        return {
            'testo': testo,
            'title': title,
            'link': link,
            'tipo': identifica_tipo_interpello(testo),
            'scadenza': scadenza,
            'source': self.name,
            'stable_id': compute_stable_id(f"argo-{customer_code}-{atto_id}"),
            'data_rilevamento': datetime.now().isoformat(),
        }

    def _url_zip_allegati(self, atto_id) -> str:
        """URL S3 pre-firmato (valido pochi minuti) dello ZIP con gli allegati dell'atto."""
        if not atto_id:
            return ''
        try:
            resp = requests.get(f"{ARGO_API_BASE}/atti/{atto_id}/allegati",
                                headers=ARGO_HEADERS, timeout=15)
            resp.raise_for_status()
            return resp.text.strip().strip('"')
        except Exception:
            return ''

    def _estrai_scadenza_da_allegati(self, atto_id) -> str:
        return estrai_scadenza_da_zip_url(self._url_zip_allegati(atto_id))


def data_archiviazione(atto: Dict) -> str:
    """Data di archiviazione dell'atto 'DD/MM/YYYY' (campo rinominato nel 2026)."""
    return atto.get('dataArchiviazioneEffettiva') or atto.get('dataArchiviazione') or ''


def lista_atti(customer_code: str, post=None) -> Dict:
    """Atti in pubblicazione sull'albo della scuola, dal più recente.
    Solleva eccezione su errore HTTP o risposta senza 'list'."""
    body = {
        "object": {
            "pubblicazioneDal": None, "pubblicazioneAl": None,
            "archiviazioneDal": None, "archiviazioneAl": None,
            "descrizione": None, "tipologiaAtto": None, "categoria": None,
        },
        "page": 0,
        "size": PAGE_SIZE,
        # Con 'dataPubblicazione,numRegistro' l'ordine è crescente qualunque sia
        # sortDesc; il solo 'dataPubblicazione' restituisce i più recenti per primi
        "sortBy": "dataPubblicazione",
        "sortDesc": True,
    }
    url = f"{ARGO_API_BASE}/atti/filters/{customer_code}"
    if post is None:
        resp = requests.post(url, json=body, headers=ARGO_HEADERS, timeout=30)
        resp.raise_for_status()
    else:
        resp = post(url, json=body, extra_headers=ARGO_HEADERS)
    data = resp.json()
    if not isinstance(data, dict) or not isinstance(data.get('list'), list):
        raise ValueError(f"risposta Argo inattesa per {customer_code}: {str(data)[:200]}")
    return data
