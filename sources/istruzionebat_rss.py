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
from pdf_utils import estrai_scadenza_da_pdf

FEED_URL = "https://www.istruzionebat.it/category/interpello/feed/"


class IstruzioneBatRssSource(BaseSource):
    name = "istruzionebat_rss"

    def fetch(self) -> List[Dict]:
        try:
            feed = feedparser.parse(FEED_URL)
            interpelli = []
            for entry in feed.entries:
                title = entry.get('title', '')
                summary = entry.get('summary', '')
                testo = f"{title} {summary}".strip()
                if not is_sostegno_primaria_infanzia(testo):
                    continue
                link = entry.get('link')
                interpelli.append({
                    'testo': testo,
                    'title': title,
                    'link': link,
                    'tipo': identifica_tipo_interpello(testo),
                    'scadenza': estrai_scadenza(testo) or (estrai_scadenza_da_pdf(link) if link and link.lower().endswith('.pdf') else ''),
                    'source': self.name,
                    'stable_id': compute_stable_id(testo),
                    'data_rilevamento': datetime.now().isoformat(),
                })
            return interpelli
        except Exception as e:
            print(f"[{self.name}] Errore: {e}")
            return []
