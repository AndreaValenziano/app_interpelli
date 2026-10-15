"""Le sorgenti rotte devono farsi notare (prima restituivano [] con un print)."""
import time
import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from sources.istruzionebat_rss import IstruzioneBatRssSource
from sources.scuolainterpelli_rss import ScuolaInterppelliRssSource


def _feed(entries, **extra):
    feed = MagicMock()
    feed.entries = entries
    feed.get.side_effect = lambda k, d=None: extra.get(k, d)
    return feed


def _voce(giorno):
    return {'title': 'Avviso', 'summary': '', 'link': 'https://x.it/a',
            'published_parsed': time.struct_time((giorno.year, giorno.month, giorno.day,
                                                  0, 0, 0, 0, 0, 0))}


class _Voce(dict):
    def __getattr__(self, k):
        return self[k]


class TestIstruzioneBatRss(unittest.TestCase):

    def test_feed_fermo_segnalato(self):
        src = IstruzioneBatRssSource()
        src._controlla_aggiornamento(_feed([_Voce(_voce(date(2026, 2, 10)))]),
                                     oggi=date(2026, 10, 15))
        self.assertEqual(len(src.errori), 1)
        self.assertIn('10/02/2026', src.errori[0])

    def test_feed_aggiornato_nessun_errore(self):
        src = IstruzioneBatRssSource()
        src._controlla_aggiornamento(_feed([_Voce(_voce(date(2026, 10, 14)))]),
                                     oggi=date(2026, 10, 15))
        self.assertEqual(src.errori, [])

    def test_errore_di_rete_segnalato(self):
        src = IstruzioneBatRssSource()
        with patch('sources.istruzionebat_rss.feedparser.parse', side_effect=OSError('down')):
            self.assertEqual(src.fetch(), [])
        self.assertTrue(src.errori)


class TestScuolaInterpelliRss(unittest.TestCase):

    def test_feed_vuoto_segnalato(self):
        src = ScuolaInterppelliRssSource()
        with patch('sources.scuolainterpelli_rss.feedparser.parse', return_value=_feed([])):
            self.assertEqual(src.fetch(), [])
        self.assertTrue(src.errori)


if __name__ == '__main__':
    unittest.main()
