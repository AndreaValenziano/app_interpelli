import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from .base import BaseSource

FILE_MAC = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'trasparenzascuole_mac.json')
# Il Mac aggiorna il file almeno ogni 6 ore: oltre questa età è spento o non riesce a pubblicare
ORE_FILE_FERMO = 24


class TrasparenzascuoleMacSource(BaseSource):
    """Interpelli di trasparenzascuole letti dal Mac (tools/mac_trasparenzascuole.py) e
    pubblicati nel repo: il WAF Cloudflare blocca le richieste dirette da GitHub Actions."""
    name = "trasparenzascuole_mac"

    def fetch(self, reporter=None, adesso: Optional[datetime] = None) -> List[Dict]:
        try:
            with open(FILE_MAC, encoding='utf-8') as f:
                dati = json.load(f)
            for errore in dati.get('errori', []):
                self.segnala_errore(f"Dal Mac: {errore}")
            aggiornato = datetime.fromisoformat(dati['aggiornato'])
            if (adesso or datetime.now()) - aggiornato > timedelta(hours=ORE_FILE_FERMO):
                self.segnala_errore(f"Mac fermo: ultimo controllo del {aggiornato.strftime('%d/%m/%Y %H:%M')}")
            return dati['interpelli']
        except FileNotFoundError:
            self.segnala_errore("File del Mac assente: nessun controllo di trasparenzascuole")
        except (ValueError, KeyError) as e:
            self.segnala_errore(f"File del Mac non valido: {e}")
        return []
