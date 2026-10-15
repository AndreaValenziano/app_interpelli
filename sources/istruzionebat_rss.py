import feedparser
from datetime import date, datetime
from typing import List, Dict, Optional

from .base import BaseSource
from filtering import (
    is_sostegno_primaria_infanzia,
    identifica_tipo_interpello,
    estrai_scadenza,
    compute_stable_id,
)
FEED_URL = "https://www.istruzionebat.it/category/interpello/feed/"


# Oltre questa età dell'ultima voce il feed è considerato fermo (a febbraio 2026
# il feed ha smesso di aggiornarsi mentre la pagina indice continuava)
GIORNI_FEED_FERMO = 30


class IstruzioneBatRssSource(BaseSource):
    name = "istruzionebat_rss"

    def fetch(self, reporter=None) -> List[Dict]:
        self._reporter = reporter
        try:
            feed = feedparser.parse(FEED_URL)
            interpelli = []
            for entry in feed.entries:
                title = entry.get('title', '')
                summary = entry.get('summary', '')
                testo = f"{title} {summary}".strip()
                if not is_sostegno_primaria_infanzia(testo):
                    if self._reporter:
                        self._reporter.record_rejected({
                            'testo': testo, 'title': title,
                            'link': entry.get('link'), 'tipo': '',
                            'scadenza': '', 'source': self.name,
                            'stable_id': '', 'data_rilevamento': datetime.now().isoformat(),
                        }, 'codici_non_target', self.name)
                    continue
                link = entry.get('link')
                interpelli.append({
                    'testo': testo,
                    'title': title,
                    'link': link,
                    'tipo': identifica_tipo_interpello(testo),
                    # Scadenza dal testo; il fallback via link/PDF avviene post-dedup
                    # (link_resolver) solo per gli interpelli nuovi
                    'scadenza': estrai_scadenza(testo),
                    'source': self.name,
                    'stable_id': compute_stable_id(testo),
                    'data_rilevamento': datetime.now().isoformat(),
                })
            self._controlla_aggiornamento(feed)
            return interpelli
        except Exception as e:
            self.segnala_errore(f"Errore: {e}")
            return []

    def _controlla_aggiornamento(self, feed, oggi: Optional[date] = None) -> None:
        if not feed.entries:
            self.segnala_errore(f"Feed vuoto o illeggibile: {feed.get('bozo_exception', '')}")
            return
        date_voci = [date(*e.published_parsed[:3]) for e in feed.entries
                     if e.get('published_parsed')]
        if not date_voci:
            return
        ultima = max(date_voci)
        if ((oggi or date.today()) - ultima).days > GIORNI_FEED_FERMO:
            self.segnala_errore(f"Feed fermo: ultima voce del {ultima.strftime('%d/%m/%Y')}")
