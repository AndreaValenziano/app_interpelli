"""Test del parser di scuolainterpelli.it (HTML reale del feed, ottobre 2026)."""
import unittest
from datetime import date

from sources.scuolainterpelli_rss import ScuolaInterppelliRssSource


def _sezione(provincia, voci):
    righe = ''.join(
        f'<p class="wp-block-paragraph">{codici} &#8211; <a href="{link}">VISUALIZZA INTERPELLI</a></p>'
        f'<p class="wp-block-paragraph"><em>{data}</em></p>'
        for codici, link, data in voci)
    return f'<h3>Interpelli pubblicati da: <strong>{provincia}</strong></h3>{righe}'


def _html(*sezioni):
    return '<h2>PUGLIA</h2>' + ''.join(sezioni) + '<h2>SARDEGNA</h2>'


EEEE_ARGO = 'https://www.portaleargo.it/albopretorio/online/#/SC21815/atti/4685557'
HOMEPAGE = 'https://www.icminervinomurge.edu.it/'
OGGI = date(2026, 10, 13)


class TestParse(unittest.TestCase):

    def setUp(self):
        self.src = ScuolaInterppelliRssSource()

    def _parse(self, html):
        return self.src._parse_html(html, oggi=OGGI)

    def test_voce_bat(self):
        [ip] = self._parse(_html(_sezione('BARLETTA-ANDRIA-TRANI',
                                          [('EEEE', EEEE_ARGO, '12 ottobre 2026')])))
        self.assertEqual(ip['link'], EEEE_ARGO)
        self.assertEqual(ip['tipo'], 'POSTO COMUNE PRIMARIA (EEEE)')
        self.assertIn('12/10/2026', ip['title'])
        self.assertIn('Argo SC21815', ip['title'])
        self.assertNotIn('VISUALIZZA', ip['title'])

    def test_stesso_testo_link_generico_date_diverse_sono_interpelli_diversi(self):
        """'ADEE – VISUALIZZA INTERPELLI' con la homepage della scuola: il testo è
        identico ogni volta, l'ID testuale bloccava per sempre gli interpelli successivi."""
        a = self._parse(_html(_sezione('BARLETTA-ANDRIA-TRANI', [('ADEE', HOMEPAGE, '12 ottobre 2026')])))
        b = self._parse(_html(_sezione('BARLETTA-ANDRIA-TRANI', [('ADEE', HOMEPAGE, '13 ottobre 2026')])))
        self.assertNotEqual(a[0]['stable_id'], b[0]['stable_id'])

    def test_stessa_voce_in_due_numeri_del_feed_stesso_id(self):
        a = self._parse(_html(_sezione('BARLETTA-ANDRIA-TRANI', [('ADEE', HOMEPAGE, '12 ottobre 2026')])))
        b = self._parse(_html(_sezione('BARLETTA-ANDRIA-TRANI', [('ADEE', HOMEPAGE, '12 ottobre 2026')])))
        self.assertEqual(a[0]['stable_id'], b[0]['stable_id'])

    def test_voci_vecchie_ignorate(self):
        """Il feed conserva ~2 settimane di numeri: interpelli di più giorni fa sono
        scaduti (finestre di 24 ore) e non vanno notificati."""
        self.assertEqual(self._parse(_html(_sezione('BARLETTA-ANDRIA-TRANI',
                                                    [('ADEE', HOMEPAGE, '5 ottobre 2026')]))), [])

    def test_altre_province_ignorate(self):
        html = _html(_sezione('BARI', [('EEEE', 'https://www.uspbari.it/', '12 ottobre 2026')]))
        self.assertEqual(self._parse(html), [])

    def test_codice_non_target_ignorato(self):
        html = _html(_sezione('BARLETTA-ANDRIA-TRANI',
                              [('BA02', 'https://www.istruzionebat.it/', '12 ottobre 2026')]))
        self.assertEqual(self._parse(html), [])

    def test_provincia_con_andria_nel_nome_non_e_bat(self):
        # 'ALESSANDRIA' contiene 'ANDRIA': serve il confronto per parola intera
        html = _html(_sezione('ALESSANDRIA', [('EEEE', 'https://x.it/a', '12 ottobre 2026')]))
        self.assertEqual(self._parse(html), [])


if __name__ == '__main__':
    unittest.main()
