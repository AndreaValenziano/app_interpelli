"""Test del passaggio Mac → repo → monitor per trasparenzascuole."""
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from sources import trasparenzascuole_mac as modulo
from tools.mac_trasparenzascuole import da_pubblicare

ADESSO = datetime(2026, 11, 9, 12, 0)
IP = {'title': 'x', 'stable_id': '1', 'data_rilevamento': 'oggi'}


class TestSorgenteMac(unittest.TestCase):
    def _leggi(self, dati=None):
        with tempfile.TemporaryDirectory() as d:
            file = os.path.join(d, 'mac.json')
            if dati is not None:
                with open(file, 'w') as f:
                    json.dump(dati, f)
            with patch.object(modulo, 'FILE_MAC', file):
                s = modulo.TrasparenzascuoleMacSource()
                return s.fetch(adesso=ADESSO), s.errori

    def test_legge_interpelli_ed_errori(self):
        interpelli, errori = self._leggi({'aggiornato': ADESSO.isoformat(), 'errori': ['HTTP 500'], 'interpelli': [IP]})
        self.assertEqual(interpelli, [IP])
        self.assertEqual(errori, ['Dal Mac: HTTP 500'])

    def test_mac_fermo_segnalato_ma_interpelli_tenuti(self):
        vecchio = (ADESSO - timedelta(hours=25)).isoformat()
        interpelli, errori = self._leggi({'aggiornato': vecchio, 'interpelli': [IP]})
        self.assertEqual(interpelli, [IP])
        self.assertIn('Mac fermo', errori[0])

    def test_file_assente_segnalato(self):
        interpelli, errori = self._leggi()
        self.assertEqual(interpelli, [])
        self.assertTrue(errori)


class TestDaPubblicare(unittest.TestCase):
    def test_solo_novita_o_battito(self):
        attuali = {'aggiornato': ADESSO.isoformat(), 'errori': [], 'interpelli': [IP]}
        stessi = {**attuali, 'interpelli': [{**IP, 'data_rilevamento': 'domani'}]}
        self.assertFalse(da_pubblicare(stessi, attuali, ADESSO + timedelta(hours=1)))
        self.assertTrue(da_pubblicare(stessi, attuali, ADESSO + timedelta(hours=6)))
        self.assertTrue(da_pubblicare({**attuali, 'interpelli': []}, attuali, ADESSO))
        self.assertTrue(da_pubblicare(attuali, {}, ADESSO))


if __name__ == '__main__':
    unittest.main()
