"""Test del merge dell'archivio dashboard."""
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from dashboard import aggiorna_dashboard


def _rec(sid, scadenza='', archiviato=False):
    return {
        'title': 'Interpello ADEE', 'tipo': 'sostegno', 'scadenza': scadenza,
        'link': f'https://scuola.example/{sid}', 'source': 'test',
        'stable_id': sid, 'data_rilevamento': datetime.now().isoformat(),
        'testo': 'x', 'archiviato': archiviato,
    }


class TestMergeArchivio(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.docs = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _leggi(self):
        return json.loads((self.docs / 'interpelli.json').read_text(encoding='utf-8'))

    def test_scadenza_risolta_dopo_aggiorna_il_record(self):
        aggiorna_dashboard([_rec('a')], docs_dir=self.docs)
        aggiorna_dashboard([_rec('a', scadenza='29/10/2025')], docs_dir=self.docs)
        recs = self._leggi()
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]['scadenza'], '29/10/2025')

    def test_scadenza_esistente_non_viene_sovrascritta_da_vuota(self):
        aggiorna_dashboard([_rec('a', scadenza='29/10/2025')], docs_dir=self.docs)
        aggiorna_dashboard([_rec('a')], docs_dir=self.docs)
        self.assertEqual(self._leggi()[0]['scadenza'], '29/10/2025')

    def test_flag_archiviato_viene_integrato(self):
        aggiorna_dashboard([_rec('a')], docs_dir=self.docs)
        aggiorna_dashboard([_rec('a', archiviato=True)], docs_dir=self.docs)
        self.assertTrue(self._leggi()[0]['archiviato'])

    def test_record_nuovo_viene_aggiunto(self):
        aggiorna_dashboard([_rec('a')], docs_dir=self.docs)
        aggiorna_dashboard([_rec('b')], docs_dir=self.docs)
        self.assertEqual(len(self._leggi()), 2)


if __name__ == '__main__':
    unittest.main()
