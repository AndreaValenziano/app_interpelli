"""Link generici (homepage della scuola) ricondotti all'atto Argo specifico.

Caso reale: istruzionebat.it e scuolainterpelli.it hanno pubblicato l'ADEE della
Pietrocola-Mazzini (atto Argo 4666558, scadenza 08/10/2026) col solo link
https://www.icminervinomurge.edu.it/: niente scadenza e due doppioni in dashboard."""
import unittest
from datetime import date
from unittest.mock import patch

import link_resolver
from link_resolver import link_specifico_argo


def _atto(id_, descrizione, pubblicazione):
    return {'id': id_, 'descrizione': descrizione, 'dataPubblicazione': pubblicazione,
            'dataArchiviazioneEffettiva': '31/12/2099', 'annullato': False}


LISTING = {'totalRows': 4, 'list': [
    _atto(4690295, 'Interpello nazionale per supplenza docente su classe di concorso EEEE', '13/10/2026'),
    _atto(4685557, 'Interpello nazionale per supplenza docente su classe di concorso EEEE', '12/10/2026'),
    _atto(4680000, 'Verbale esito interpello ADEE del 07/10/2026', '08/10/2026'),
    _atto(4666558, 'Interpello nazionale per supplenza docente su classe di concorso ADEE', '05/10/2026'),
]}
HOME = 'https://www.icminervinomurge.edu.it/'


class TestLinkSpecificoArgo(unittest.TestCase):

    def setUp(self):
        link_resolver._argo_listing_cache.clear()
        patcher = patch.object(link_resolver, 'lista_atti', return_value=LISTING)
        self.lista = patcher.start()
        self.addCleanup(patcher.stop)

    def test_unico_atto_con_lo_stesso_codice(self):
        self.assertEqual(link_specifico_argo(HOME, ['ADEE'], date(2026, 10, 1), date(2026, 10, 15)),
                         'https://www.portaleargo.it/albopretorio/online/#/SC21815/atti/4666558')
        self.lista.assert_called_once_with('SC21815')

    def test_piu_atti_ambigui_nessun_link(self):
        self.assertEqual(link_specifico_argo(HOME, ['EEEE'], date(2026, 10, 1), date(2026, 10, 15)), '')

    def test_la_data_di_pubblicazione_scioglie_l_ambiguita(self):
        self.assertEqual(link_specifico_argo(HOME, ['EEEE'], date(2026, 10, 12), date(2026, 10, 12)),
                         'https://www.portaleargo.it/albopretorio/online/#/SC21815/atti/4685557')

    def test_fuori_finestra_nessun_link(self):
        self.assertEqual(link_specifico_argo(HOME, ['ADEE'], date(2026, 10, 10), date(2026, 10, 15)), '')

    def test_scuola_non_argo_o_sconosciuta(self):
        self.assertEqual(link_specifico_argo('https://www.icmargheritadisavoia.edu.it/', ['ADEE'],
                                             date(2026, 10, 1), date(2026, 10, 15)), '')
        self.assertEqual(link_specifico_argo('https://www.istruzionebat.it/', ['ADEE'],
                                             date(2026, 10, 1), date(2026, 10, 15)), '')
        self.lista.assert_not_called()


if __name__ == '__main__':
    unittest.main()
