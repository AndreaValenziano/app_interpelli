"""Test del parser Nuvola (struttura reale della bacheca, ottobre 2026)."""
import unittest
from datetime import date

from bs4 import BeautifulSoup

from sources.nuvola_albo import NuvolaAlboSource

INTESTAZIONE = ('<tr><th>Azioni</th><th>Visualizza</th><th>Oggetto</th>'
                '<th>Data pubblicazione su bacheca</th><th>Registro</th></tr>'
                '<tr><td>Togli filtri</td><td>Togli filtri</td><td>Uguale Diverso</td>'
                '<td>Uguale Diverso</td><td>Uguale Diverso</td></tr>')


def _riga(oggetto, pubblicazione, doc_id):
    return (f'<tr><td><a href="/bacheca-digitale/{doc_id}/documento/BAIC86000B/1">apri</a></td>'
            f'<td></td><td>{oggetto}</td><td>{pubblicazione}</td><td>REGISTRO PROTOCOLLO</td></tr>')


def _soup(*righe):
    return BeautifulSoup(f'<table>{INTESTAZIONE}{"".join(righe)}</table>', 'html.parser')


class TestParseTabella(unittest.TestCase):

    def _parse(self, soup):
        return NuvolaAlboSource()._parse_tabella(soup, 'BAIC86000B', 'Don Bosco',
                                                 oggi=date(2026, 10, 15))

    def test_oggetto_dalla_colonna_indicata_nell_intestazione(self):
        [ip] = self._parse(_soup(_riga('INTERPELLO ADEE', '14-10-2026', 3700)))
        self.assertEqual(ip['title'], '[Don Bosco] INTERPELLO ADEE')
        self.assertEqual(ip['link'], 'https://nuvola.madisoft.it/bacheca-digitale/3700/documento/BAIC86000B/1')

    def test_pubblicazioni_vecchie_ignorate(self):
        """La bacheca tiene 'in pubblicazione' interpelli di mesi prima (archiviazione
        anche dopo 5 anni): sono chiusi da tempo e non vanno notificati."""
        self.assertEqual(self._parse(_soup(_riga('INTERPELLO ADEE', '12-05-2026', 3698))), [])

    def test_riga_filtri_non_e_un_interpello(self):
        self.assertEqual(self._parse(_soup()), [])


if __name__ == '__main__':
    unittest.main()
