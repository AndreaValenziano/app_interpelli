import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from monitor_interpelli import InterpelliMonitor


def _interpello(sid: str, link: str = '', scadenza: str = '') -> dict:
    return {
        'testo': f'testo {sid}', 'title': f'titolo {sid}', 'link': link,
        'tipo': 'POSTO COMUNE PRIMARIA (EEEE)', 'scadenza': scadenza,
        'source': 'test', 'stable_id': sid, 'data_rilevamento': '2026-07-02T10:00:00',
    }


class TestFiltraNuoviInterpelli(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.monitor = InterpelliMonitor(config_file='/nonexistent.json', dry_run=True)
        self.monitor.interpelli_salvati = self.tmp.name

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_non_salva_stato(self):
        """filtra_nuovi_interpelli non deve scrivere lo stato: si salva dopo l'invio."""
        nuovi, stato = self.monitor.filtra_nuovi_interpelli([_interpello('a')])
        self.assertEqual(len(nuovi), 1)
        self.assertFalse(os.path.exists(self.tmp.name))
        self.assertIn('a', stato['ids'])

    def test_dedup_per_stable_id(self):
        _, stato = self.monitor.filtra_nuovi_interpelli([_interpello('a')])
        self.monitor.save_interpelli_visti(stato)
        nuovi, _ = self.monitor.filtra_nuovi_interpelli([_interpello('a')])
        self.assertEqual(nuovi, [])

    def test_link_generico_non_sopprime_interpelli_successivi(self):
        """Due interpelli diversi della stessa scuola con lo stesso link generico
        (es. albo Argo senza id) devono essere notificati entrambi."""
        link_generico = 'https://www.portaleargo.it/albopretorio/online/#/?customerCode=SC27220'
        _, stato = self.monitor.filtra_nuovi_interpelli([_interpello('a', link=link_generico)])
        self.monitor.save_interpelli_visti(stato)
        nuovi, _ = self.monitor.filtra_nuovi_interpelli([_interpello('b', link=link_generico)])
        self.assertEqual(len(nuovi), 1)

    def test_link_specifico_dedupa_cross_sorgente(self):
        """Stesso interpello da due sorgenti (stable_id diversi, stesso link specifico)
        deve essere notificato una sola volta."""
        link = 'https://www.istruzionebat.it/2026/07/01/interpello-eeee/'
        _, stato = self.monitor.filtra_nuovi_interpelli([_interpello('a', link=link)])
        self.monitor.save_interpelli_visti(stato)
        nuovi, _ = self.monitor.filtra_nuovi_interpelli([_interpello('b', link=link)])
        self.assertEqual(nuovi, [])


if __name__ == '__main__':
    unittest.main()
