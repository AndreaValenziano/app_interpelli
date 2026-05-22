import hashlib
import re
from typing import List

CODICI_OBIETTIVO: List[str] = ['ADEE', 'ADAA', 'EEEE', 'AAAA']


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
    patterns = [
        r'fino al (\d{2}/\d{2}/\d{4})',
        r'entro il (\d{2}/\d{2}/\d{4})',
        r'dal (\d{2}/\d{2}/\d{4}) al (\d{2}/\d{2}/\d{4})',
        r'(\d{2}/\d{2}/\d{4})',
    ]
    for pattern in patterns:
        match = re.search(pattern, testo)
        if match:
            return match.group(1) if match.lastindex == 1 else match.group(2)
    return 'Non specificata'


def normalizza_testo(testo: str) -> str:
    return re.sub(r'\s+', ' ', testo.lower()).strip()


def compute_stable_id(testo: str) -> str:
    return hashlib.sha256(normalizza_testo(testo).encode('utf-8')).hexdigest()
