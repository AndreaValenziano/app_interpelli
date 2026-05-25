import hashlib
import re
from datetime import date, datetime
from typing import List, Optional

CODICI_OBIETTIVO: List[str] = ['ADEE', 'ADAA', 'EEEE', 'AAAA']

# Gruppo data: DD sep MM sep YYYY con separatori . / -
_SEP = r'[./\-]'
_DC  = rf'(\d{{2}}{_SEP}\d{{2}}{_SEP}\d{{4}})'   # date con cattura
_D   = rf'\d{{2}}{_SEP}\d{{2}}{_SEP}\d{{4}}'      # date senza cattura

# Pattern qualificati: corrispondono solo a scadenze per la domanda/candidatura.
# Non includono pattern generici come "\bal\b DATE" (catturano date di fine contratto).
# Ordine: da più specifico a più generico — primo match vince.
_QUALIFIED_PATTERNS = [
    # "ore HH:MM del [giorno] DATE" — forma canonica negli interpelli scolastici
    rf'ore\s+\d{{1,2}}[:.]?\d{{0,2}}\s+del\s+(?:giorno\s+)?{_DC}',
    # "entro (e non oltre) le ore X del [giorno] DATE"
    rf'entro\s+(?:e\s+non\s+oltre\s+)?le\s+ore\s+\d{{1,2}}[:.]?\d{{0,2}}\s+del\s+(?:giorno\s+)?{_DC}',
    # "scadenza|termine della/e domanda/candidatura: DATE"
    rf'(?:scadenza|termine)\s+(?:(?:della\s+)?(?:presentazione\s+)?)?(?:domand[ae]|candidatur[ae])\s*:?\s*{_DC}',
    # "presentazione della domanda: DATE"
    rf'presentazione\s+(?:della\s+)?domand[ae]\s*:?\s*{_DC}',
    # "(domanda|candidatura)... entro ... DATE" — non attraversa punto/punto e virgola
    rf'(?:domand[ae]|candidatur[ae])\s+[^.;]{{0,80}}?\bentro\b\s+[^.;]{{0,40}}?\b{_DC}',
    # "(presentare|inviare|pervenire|trasmettere|disponibilità) ... entro ... DATE"
    rf'(?:presentare|inviare|invia(?:te|to)|far\s+pervenire|pervenire|trasmettere|disponibilit[àa])\s+[^.;]{{0,80}}?\bentro\b\s+[^.;]{{0,40}}?\b{_DC}',
    # "manifestazione di interesse entro DATE"
    rf'manifestazion[ei]\s+di\s+interesse\s+[^.;]{{0,60}}?\bentro\b\s+[^.;]{{0,40}}?\b{_DC}',
    # "entro il termine perentorio del DATE"
    rf'entro\s+(?:e\s+non\s+oltre\s+)?il\s+termine\s+(?:perentorio\s+)?(?:del\s+)?{_DC}',
]


_LIKELY_INTERPELLO_KEYWORDS = (
    'interpell',        # interpello/interpelli
    'supplenz',         # supplenza/supplenze
    'incarico',
    'messa a disposizione',
)


def is_likely_interpello(testo: str) -> bool:
    """True se il testo contiene parole chiave che suggeriscono un interpello/supplenza.
    Usato nei fetcher generici per limitare il logging degli scarti a casi 'vicini al match'."""
    tl = testo.lower()
    return any(k in tl for k in _LIKELY_INTERPELLO_KEYWORDS)


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
    """Estrae la scadenza domanda da testo libero. Riconosce solo formule qualificate
    (es. 'entro le ore X del DD/MM/YYYY', 'domanda entro il DD/MM/YYYY').
    Non estrae date di fine contratto ('supplenza al X', 'dal X al Y').
    Ritorna 'DD/MM/YYYY' o '' se non trovata."""
    testo_norm = re.sub(r'\s+', ' ', testo)
    for pattern in _QUALIFIED_PATTERNS:
        m = re.search(pattern, testo_norm, re.IGNORECASE)
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
