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

    def test_dettagli_salvati_e_testo_documento_no(self):
        rec = dict(_rec('a'), dettagli={'ora_scadenza': '12:00', 'ore': '24 h/sett'},
                   testo_documento='testo lungo del PDF')
        aggiorna_dashboard([rec], docs_dir=self.docs)
        [salvato] = self._leggi()
        self.assertEqual(salvato['dettagli'], {'ora_scadenza': '12:00', 'ore': '24 h/sett'})
        self.assertNotIn('testo_documento', salvato)
        self.assertIn('dettagli', (self.docs / 'index.html').read_text(encoding='utf-8'))

    def test_link_generico_sostituito_da_quello_specifico(self):
        rec = dict(_rec('a'), link='https://www.icminervinomurge.edu.it/')
        aggiorna_dashboard([rec], docs_dir=self.docs)
        argo = 'https://www.portaleargo.it/albopretorio/online/#/SC21815/atti/4666558'
        aggiorna_dashboard([dict(rec, link=argo, scadenza='08/10/2026')], docs_dir=self.docs)
        [salvato] = self._leggi()
        self.assertEqual(salvato['link'], argo)
        self.assertEqual(salvato['scadenza'], '08/10/2026')

    def test_doppioni_con_lo_stesso_atto_accorpati(self):
        argo = 'https://www.portaleargo.it/albopretorio/online/#/SC21815/atti/4666558'
        aggiorna_dashboard([dict(_rec('a'), link=argo),
                            dict(_rec('b'), link=argo.replace('#/SC21815/atti/4666558',
                                 '#/dettaglio-atto?customerCode=SC21815&id=4666558'),
                                 scadenza='08/10/2026')], docs_dir=self.docs)
        recs = self._leggi()
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]['scadenza'], '08/10/2026')

    def test_supplenza_gia_iniziata_probabilmente_scaduto(self):
        from dashboard import _genera_html
        rec = dict(_rec('a'), testo='ADEE supplenza dal 01/10/2026 al 30/11/2026')
        _genera_html([rec], oggi=datetime(2026, 10, 15).date())
        self.assertEqual(rec['_stato'], 'stantio')

    def test_supplenza_appena_iniziata_resta_da_verificare(self):
        from dashboard import _genera_html
        rec = dict(_rec('a'), dettagli={'periodo': 'dal 14/10/2026 al 30/11/2026'})
        _genera_html([rec], oggi=datetime(2026, 10, 15).date())
        self.assertEqual(rec['_stato'], 'ignota')

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
