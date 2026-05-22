import hashlib
import re
from datetime import date, datetime
from typing import List, Optional

CODICI_OBIETTIVO: List[str] = ['ADEE', 'ADAA', 'EEEE', 'AAAA']

# Gruppo data: DD sep MM sep YYYY con separatori . / -
_SEP = r'[./\-]'
_DC  = rf'(\d{{2}}{_SEP}\d{{2}}{_SEP}\d{{4}})'   # date con cattura
_D   = rf'\d{{2}}{_SEP}\d{{2}}{_SEP}\d{{4}}'      # date senza cattura

# Ordine: keyword + data prima, poi "dal X al Y" (prende fine), poi qualsiasi data
_SCADENZA_PATTERNS = [
    rf'(?:fino\s+al|entro\s+il|\bal\b|scadenza\s*:?|termine\s*:?)\s*{_DC}',
    rf'dal\s+{_D}\s+al\s+{_DC}',
    _DC,
]


def is_sostegno_primaria_infanzia(testo: str) -> bool:
    testo_upper = testo.upper()
    return any(k in testo_upper for k in CODICI_OBIETTIVO)


def identifica_tipo_interpello(testo: str) -> str:
    testo_upper = testo.upper()
    tipi = []
    if 'ADEE' in testo_upper:
        tipi.append('SOSTEGNO PRIMARIA (ADEE)')
    if 'ADAA' in testo_upper:
        tipi.append('SOSTEGNO INFANZIA (ADAA)')
    if 'EEEE' in testo_upper:
        tipi.append('POSTO COMUNE PRIMARIA (EEEE)')
    if 'AAAA' in testo_upper:
        tipi.append('POSTO COMUNE INFANZIA (AAAA)')
    return ' + '.join(tipi) if tipi else 'PRIMARIA/INFANZIA'


def estrai_scadenza(testo: str) -> str:
    """Estrae la scadenza da testo libero. Gestisce separatori ./- e keyword (al/entro il/...).
    Ritorna 'DD/MM/YYYY' o '' se non trovata."""
    for pattern in _SCADENZA_PATTERNS:
        m = re.search(pattern, testo, re.IGNORECASE)
        if m:
            raw = m.group(1)
            return re.sub(r'[.\-]', '/', raw)
    return ''


def parse_data(s: str) -> Optional[date]:
    """Parsa 'DD/MM/YYYY' → date. Ritorna None se non parsabile."""
    if not s:
        return None
    try:
        return datetime.strptime(s, '%d/%m/%Y').date()
    except (ValueError, TypeError):
        return None


def scadenza_passata(scadenza_str: str, oggi: Optional[date] = None) -> bool:
    """True solo se la scadenza è parsabile e < oggi. False se non parsabile (non scartare)."""
    d = parse_data(scadenza_str)
    if d is None:
        return False
    return d < (oggi or date.today())


def normalizza_testo(testo: str) -> str:
    return re.sub(r'\s+', ' ', testo.lower()).strip()


def compute_stable_id(testo: str) -> str:
    return hashlib.sha256(normalizza_testo(testo).encode('utf-8')).hexdigest()
