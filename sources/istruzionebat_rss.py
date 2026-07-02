import feedparser
from datetime import datetime
from typing import List, Dict

from .base import BaseSource
from filtering import (
    is_sostegno_primaria_infanzia,
    identifica_tipo_interpello,
    estrai_scadenza,
    compute_stable_id,
)
FEED_URL = "https://www.istruzionebat.it/category/interpello/feed/"


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
            return interpelli
        except Exception as e:
            print(f"[{self.name}] Errore: {e}")
            return []
