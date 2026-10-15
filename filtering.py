import hashlib
import re
from datetime import date, datetime
from typing import List, Optional
from urllib.parse import urlparse

CODICI_OBIETTIVO: List[str] = ['ADEE', 'ADAA', 'EEEE', 'AAAA']

_MESI = {
    'gennaio': 1, 'febbraio': 2, 'marzo': 3, 'aprile': 4,
    'maggio': 5, 'giugno': 6, 'luglio': 7, 'agosto': 8,
    'settembre': 9, 'ottobre': 10, 'novembre': 11, 'dicembre': 12,
}

# Data numerica: D[D] sep M[M] sep YYYY con separatori . / -
_SEP = r'[./\-]'
_D_NUM = rf'\d{{1,2}}\s*{_SEP}\s*\d{{1,2}}\s*{_SEP}\s*\d{{4}}'
# Data testuale: "3 dicembre 2025", "1° luglio 2026"
_D_TXT = rf'\d{{1,2}}°?\s+(?:{"|".join(_MESI)})\s+\d{{4}}'
_DATE = rf'(?:{_D_NUM}|{_D_TXT})'
_DC = rf'({_DATE})'   # con cattura
_D = _DATE            # senza cattura
# Giorno della settimana opzionale prima della data ("del giorno venerdì 3 dicembre 2025")
_GSETT = r'(?:(?:luned[iì]|marted[iì]|mercoled[iì]|gioved[iì]|venerd[iì]|sabato|domenica)\s+)?'
_DEL_GIORNO = rf'del\s+(?:giorno\s+)?{_GSETT}'

# Pattern qualificati: corrispondono solo a scadenze per la domanda/candidatura.
# Non includono pattern generici come "\bal\b DATE" (catturano date di fine contratto).
# Ordine: da più specifico a più generico — primo match vince.
_QUALIFIED_PATTERNS = [
    # "ore HH:MM del [giorno] DATE" — forma canonica negli interpelli scolastici
    rf'ore\s+\d{{1,2}}[:.,]?\d{{0,2}}\s+{_DEL_GIORNO}{_DC}',
    # "entro (e non oltre) le ore X del [giorno] DATE"
    rf'entro\s+(?:e\s+non\s+oltre\s+)?le\s+ore\s+\d{{1,2}}[:.,]?\d{{0,2}}\s+{_DEL_GIORNO}{_DC}',
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
    rf'entro\s+(?:e\s+non\s+oltre\s+)?il\s+termine\s+(?:perentorio\s+)?(?:{_DEL_GIORNO})?{_DC}',
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


# Codici spezzati da spazi nei titoli di istruzionebat.it ('E EEE', 'EE EE', 'AD EE'):
# ricomposti prima del confronto. Solo maiuscole, per non fondere lettere di parole.
_CODICI_SPEZZATI_RE = [
    (re.compile(r'\b' + r'\s*'.join(codice) + r'\b'), codice) for codice in CODICI_OBIETTIVO
]


def normalizza_codici(testo: str) -> str:
    """Ricompone i codici obiettivo scritti con spazi interni ('E EEE' → 'EEEE')."""
    for regex, codice in _CODICI_SPEZZATI_RE:
        testo = regex.sub(codice, testo)
    return testo


# Atti che chiudono un interpello (verbali, esiti, individuazioni, nomine): non
# candidabili anche se citano il codice. 'individuazione' da sola NON basta, compare
# anche negli avvisi ('interpello per l'individuazione di un docente').
_ESITO_RE = re.compile(
    r'\b(?:VERBAL[EI]|ESIT[OI]|ANNULLAMENTO|DECRETO\s+DI\s+(?:INDIVIDUAZIONE|NOMINA|ASSEGNAZIONE)'
    r'|ATTO\s+DI\s+(?:INDIVIDUAZIONE|NOMINA)|INDIVIDUAZIONE\s+DA\s+INTERPELLO)\b')


def is_esito_interpello(testo: str) -> bool:
    """True per verbali/esiti/nomine che chiudono un interpello."""
    return bool(_ESITO_RE.search(testo.upper()))


# Vecchi codici tipo-posto sostegno (EH = primaria, CH = infanzia). Token maiuscoli
# nel testo originale, per non confondere 'ch'/'eh' dentro parole comuni.
_CODICI_VECCHI_RE = re.compile(r'\b(EH|CH)\b')


def is_sostegno_primaria_infanzia(testo: str) -> bool:
    """True se l'interpello riguarda primaria/infanzia (sostegno o posto comune).
    Riconosce i codici GPS (ADEE/ADAA/EEEE/AAAA), i vecchi codici tipo-posto (EH/CH)
    e — in mancanza di codici — la combinazione di parole chiave grado+tipo posto.
    Meglio un falso positivo che un interpello perso."""
    testo = normalizza_codici(testo)
    testo_upper = testo.upper()
    if is_esito_interpello(testo_upper):
        return False
    if any(k in testo_upper for k in CODICI_OBIETTIVO):
        return True
    # Le graduatorie (esito di un interpello già chiuso) non sono candidabili:
    # escluse dai percorsi senza codice esplicito ('GRADUATORI' copre singolare/plurale)
    if 'GRADUATORI' in testo_upper:
        return False
    if _CODICI_VECCHI_RE.search(testo) and 'SOSTEGNO' in testo_upper:
        return True
    # Fallback keyword per interpelli senza codice esplicito
    grado = 'PRIMARIA' in testo_upper or 'INFANZIA' in testo_upper
    posto = 'SOSTEGNO' in testo_upper or 'POSTO COMUNE' in testo_upper
    return grado and posto


def identifica_tipo_interpello(testo: str) -> str:
    testo = normalizza_codici(testo)
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
    if tipi:
        return ' + '.join(tipi)
    # Nessun codice GPS: prova con vecchi codici / parole chiave
    sostegno = bool(_CODICI_VECCHI_RE.search(testo)) or 'SOSTEGNO' in testo_upper
    if 'PRIMARIA' in testo_upper:
        return 'SOSTEGNO PRIMARIA' if sostegno else 'PRIMARIA'
    if 'INFANZIA' in testo_upper:
        return 'SOSTEGNO INFANZIA' if sostegno else 'INFANZIA'
    return 'PRIMARIA/INFANZIA'


def normalizza_data(raw: str) -> str:
    """Converte una data catturata (numerica o testuale) in 'DD/MM/YYYY'.
    Ritorna '' se non valida (es. 45/13/2026)."""
    raw = raw.strip()
    m = re.match(r'(\d{1,2})°?\s+([a-zà]+)\s+(\d{4})', raw, re.IGNORECASE)
    if m:
        mese = _MESI.get(m.group(2).lower())
        if not mese:
            return ''
        candidata = f"{int(m.group(1)):02d}/{mese:02d}/{m.group(3)}"
    else:
        m = re.match(rf'(\d{{1,2}})\s*{_SEP}\s*(\d{{1,2}})\s*{_SEP}\s*(\d{{4}})', raw)
        if not m:
            return ''
        candidata = f"{int(m.group(1)):02d}/{int(m.group(2)):02d}/{m.group(3)}"
    return candidata if parse_data(candidata) else ''


def estrai_scadenza(testo: str) -> str:
    """Estrae la scadenza domanda da testo libero. Riconosce solo formule qualificate
    (es. 'entro le ore X del DD/MM/YYYY', 'domanda entro il 3 dicembre 2025').
    Non estrae date di fine contratto ('supplenza al X', 'dal X al Y').
    Ritorna 'DD/MM/YYYY' o '' se non trovata."""
    testo_norm = re.sub(r'\s+', ' ', testo)
    for pattern in _QUALIFIED_PATTERNS:
        m = re.search(pattern, testo_norm, re.IGNORECASE)
        if m:
            data = normalizza_data(m.group(1))
            if data:
                return data
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


# Atto Argo nei due formati di deep-link: '#/dettaglio-atto?customerCode=X&id=Y'
# (argo_albo, vecchi indici) e '#/SC21815/atti/Y' (istruzionebat.it, scuolainterpelli.it dal 2026)
_ARGO_NUOVO_RE = re.compile(r'#/(S[CE]\d+)/atti/(\d+)', re.IGNORECASE)
_ARGO_CODE_RE = re.compile(r'customerCode=(S[CE]\d+)', re.IGNORECASE)
_ARGO_ID_RE = re.compile(r'[?&]id=(\d+)', re.IGNORECASE)


def parse_link_argo(link: str) -> Optional[tuple]:
    """(customerCode, attoId) da un deep-link Argo in uno dei due formati, o None."""
    if not link or 'portaleargo.it' not in link.lower():
        return None
    m = _ARGO_NUOVO_RE.search(link)
    if m:
        return m.group(1).upper(), m.group(2)
    m_code, m_id = _ARGO_CODE_RE.search(link), _ARGO_ID_RE.search(link)
    if m_code and m_id:
        return m_code.group(1).upper(), m_id.group(1)
    return None


def chiave_link(link: str) -> str:
    """Chiave di dedup del link: 'argo:SC:ID' per gli atti Argo (stessa chiave per
    entrambi i formati), il link normalizzato per gli altri, '' se generico."""
    argo = parse_link_argo(link)
    if argo:
        return f"argo:{argo[0]}:{argo[1]}"
    if not is_link_dedupabile(link):
        return ''
    return link.strip().lower()


def is_link_dedupabile(link: str) -> bool:
    """True se il link identifica UN SINGOLO interpello e può essere usato per il dedup.
    I link generici (homepage di scuola, albo intero) sono condivisi da più interpelli:
    usarli per il dedup sopprimerebbe ogni interpello successivo della stessa scuola."""
    if not link:
        return False
    low = link.strip().lower()
    # Albo Argo: dedupabile solo il deep-link con id atto
    if 'portaleargo.it' in low and 'albopretorio' in low:
        return parse_link_argo(link) is not None
    # Trasparenzascuole: la pagina è per-scuola; serve il fragment per-atto
    if 'trasparenzascuole.it' in low:
        return '#atto-' in low
    try:
        p = urlparse(link)
    except ValueError:
        return False
    # Homepage nuda (nessun percorso/query/fragment) → generica
    return bool(p.path.strip('/') or p.query or p.fragment)
