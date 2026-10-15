"""Test della sorgente istruzionebat_html (rete mockata)."""
import unittest
from datetime import date
from unittest.mock import MagicMock, patch

import requests

from sources import istruzionebat_html
from sources.istruzionebat_html import IstruzioneBatHtmlSource, url_anno_scolastico

# Struttura reale della pagina a.s. 2026-2027 (ottobre 2026): voci in <h2>/<h3>
# dentro div.testolungo, codici a volte spezzati da spazi ('E EEE')
PAGINA = """
<html><body><div class="testolungo">
<h2>-Interpello nazionale per supplenza docente su classe di concorso E EEE – Posto Comune –
 <a href="https://www.portaleargo.it/albopretorio/online/#/SC21815/atti/4690295">https://www.portaleargo.it/albopretorio/online/#/SC21815/atti</a></h2>
<h2>-Interpello nazionale per supplenza docente su classe di concorso B B 0 2 CONVERSAZIONE IN LINGUA –
 <a href="https://www.portaleargo.it/albopretorio/online/#/SC12641/atti/4684220">link</a></h2>
<h3>– Interpello Nazionale per selezione personale docente di SCUOLA PRIMARIA ADEE SOSTEGNO –
 supplenza breve e saltuaria dal 01/10/2026 al 30/11/2026
 <a href="https://www.trasparenzascuole.it/Public/APDPublic_ExtV2.aspx?CF=90091020728">albo</a></h3>
<p></p>
</div></body></html>
"""


class TestUrlAnnoScolastico(unittest.TestCase):

    def test_da_settembre_anno_nuovo(self):
        self.assertEqual(url_anno_scolastico(date(2026, 9, 1)),
                         'https://www.istruzionebat.it/interpelli/a-s-2026-2027/')

    def test_fino_ad_agosto_anno_precedente(self):
        self.assertEqual(url_anno_scolastico(date(2027, 8, 31)),
                         'https://www.istruzionebat.it/interpelli/a-s-2026-2027/')


class TestFetch(unittest.TestCase):

    def _fetch(self, risposte):
        src = IstruzioneBatHtmlSource()
        with patch.object(src, '_http_get', side_effect=risposte) as get:
            risultati = src.fetch()
        return src, risultati, get

    def test_voci_h2_h3_con_codici_spezzati(self):
        _, risultati, _ = self._fetch([MagicMock(text=PAGINA)])
        self.assertEqual(len(risultati), 2)
        eeee, adee = risultati
        self.assertEqual(eeee['tipo'], 'POSTO COMUNE PRIMARIA (EEEE)')
        self.assertEqual(eeee['link'],
                         'https://www.portaleargo.it/albopretorio/online/#/SC21815/atti/4690295')
        self.assertEqual(adee['tipo'], 'SOSTEGNO PRIMARIA (ADEE)')

    def test_pagina_anno_nuovo_non_ancora_creata_usa_la_precedente(self):
        errore = requests.HTTPError('404')
        src, risultati, get = self._fetch([errore, MagicMock(text=PAGINA)])
        self.assertEqual(len(risultati), 2)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(src.errori, [])

    def test_pagina_senza_voci_segnala_errore(self):
        src, risultati, _ = self._fetch([MagicMock(text='<html><body>vuota</body></html>')])
        self.assertEqual(risultati, [])
        self.assertTrue(src.errori)


if __name__ == '__main__':
    unittest.main()
