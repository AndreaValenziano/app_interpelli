"""Test della sorgente Argo e del suo uso nel resolver (rete mockata).

Schema API reale da ottobre 2026: categoria testuale libera per scuola in
`categoriaDenominazione` (`categoria` è null), `allegati` vuoto nel listing
(solo `numAllegati`), `dataArchiviazioneEffettiva` al posto di `dataArchiviazione`.
"""
import unittest
from unittest.mock import patch

import link_resolver
from sources import argo_albo
from sources.argo_albo import ArgoAlboSource


def _atto(id_, descrizione, categoria='BANDI DI GARA E PROCEDURE DI RECLUTAMENTO',
          archiviazione='31/12/2099', **extra):
    atto = {
        'id': id_, 'codCli': 'SC21815', 'descrizione': descrizione,
        'categoriaDenominazione': categoria, 'categoria': None,
        'dataPubblicazione': '13/10/2026', 'dataArchiviazioneEffettiva': archiviazione,
        'annullato': False, 'numAllegati': 2, 'allegati': [],
    }
    atto.update(extra)
    return atto


class TestProcessAtto(unittest.TestCase):

    def setUp(self):
        self.src = ArgoAlboSource()
        self.src._reporter = None
        patcher = patch.object(ArgoAlboSource, '_estrai_scadenza_da_allegati', return_value='')
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_interpello_eeee_con_categoria_libera(self):
        ip = self.src._process_atto(_atto(
            4690295, 'Interpello nazionale per supplenza docente su classe di concorso EEEE '
                     '(Posto Comune Scuola Primaria)'), 'SC21815', 'Pietrocola')
        self.assertIsNotNone(ip)
        self.assertEqual(ip['tipo'], 'POSTO COMUNE PRIMARIA (EEEE)')
        self.assertEqual(ip['link'],
                         'https://www.portaleargo.it/albopretorio/online/#/SC21815/atti/4690295')

    def test_categoria_qualsiasi_purche_interpello(self):
        ip = self.src._process_atto(_atto(1, 'Interpello ADEE sostegno primaria', categoria=None),
                                    'SC21815', 'X')
        self.assertIsNotNone(ip)

    def test_atto_non_interpello_ignorato(self):
        self.assertIsNone(self.src._process_atto(
            _atto(2, 'Decreto di assegnazione docenti di Sostegno scuola primaria'), 'SC21815', 'X'))

    def test_verbale_esito_escluso(self):
        self.assertIsNone(self.src._process_atto(
            _atto(3, 'VERBALE DELLE OPERAZIONI PER L\'INDIVIDUAZIONE DI N.1 DOCENTE DI SOSTEGNO '
                     'DI SCUOLA PRIMARIA (INTERPELLO DEL 05/10/2026)'), 'SC21815', 'X'))

    def test_archiviato_escluso(self):
        self.assertIsNone(self.src._process_atto(
            _atto(4, 'Interpello EEEE', archiviazione='01/01/2020'), 'SC21815', 'X'))

    def test_annullato_escluso(self):
        self.assertIsNone(self.src._process_atto(
            _atto(5, 'Interpello EEEE', annullato=True), 'SC21815', 'X'))

    def test_codice_altra_classe_escluso_senza_scaricare_allegati(self):
        with patch.object(argo_albo, 'testo_da_zip_url') as zip_mock:
            self.assertIsNone(self.src._process_atto(
                _atto(6, 'Interpello nazionale per supplenza docente su classe di concorso BA02'),
                'SC12641', 'X'))
        zip_mock.assert_not_called()

    def test_interpello_senza_codice_legge_gli_allegati(self):
        """Il listing non ha più i nomi degli allegati: se la descrizione non dice la
        classe di concorso, il codice si cerca nei PDF."""
        with patch.object(ArgoAlboSource, '_url_zip_allegati', return_value='https://s3/zip'), \
             patch.object(argo_albo, 'testo_da_zip_url',
                          return_value='interpello_adee.pdf Avviso supplenza ADEE. La domanda '
                                       'entro le ore 11:00 del 20/10/2026'):
            ip = self.src._process_atto(_atto(7, 'Interpello nazionale per supplenza docente'),
                                        'SC21815', 'X')
        self.assertIsNotNone(ip)
        self.assertEqual(ip['tipo'], 'SOSTEGNO PRIMARIA (ADEE)')
        self.assertEqual(ip['scadenza'], '20/10/2026')

    def test_interpello_senza_codice_e_allegati_di_altra_classe(self):
        with patch.object(ArgoAlboSource, '_url_zip_allegati', return_value='https://s3/zip'), \
             patch.object(argo_albo, 'testo_da_zip_url', return_value='classe A022 lettere'):
            self.assertIsNone(self.src._process_atto(
                _atto(8, 'Interpello nazionale per supplenza docente'), 'SC21815', 'X'))


class TestFetchScuola(unittest.TestCase):

    def test_ordina_per_data_pubblicazione_decrescente(self):
        """'dataPubblicazione,numRegistro' viene ordinato in modo crescente qualunque sia
        sortDesc: con size=100 si perdevano gli atti più recenti delle scuole grandi."""
        catturato = {}

        class Resp:
            def json(self):
                return {'totalRows': 0, 'list': []}

        def fake_post(url, json=None, extra_headers=None):
            catturato['body'] = json
            return Resp()

        src = ArgoAlboSource()
        with patch.object(src, '_http_post', side_effect=fake_post):
            src._fetch_scuola({'nome': 'X', 'params': {'customerCode': 'SE29246'}})
        self.assertEqual(catturato['body']['sortBy'], 'dataPubblicazione')

    def test_risposta_senza_list_segnala_errore(self):
        class Resp:
            def json(self):
                return {'error': 'boom'}

        src = ArgoAlboSource()
        with patch.object(src, '_http_post', return_value=Resp()):
            with self.assertRaises(ValueError):
                src._fetch_scuola({'nome': 'X', 'params': {'customerCode': 'SE29246'}})


class TestResolverArgo(unittest.TestCase):

    NUOVO = 'https://www.portaleargo.it/albopretorio/online/#/SC21815/atti/4690295'

    def setUp(self):
        link_resolver._argo_listing_cache.clear()
        link_resolver._cache.clear()

    def test_risolve_link_nuovo_formato(self):
        with patch.object(link_resolver, '_risolvi_argo_atto', return_value='15/10/2026') as m:
            self.assertEqual(link_resolver._risolvi(self.NUOVO), '15/10/2026')
        m.assert_called_once_with('4690295')

    def test_archiviato_usa_data_archiviazione_effettiva(self):
        listing = {'totalRows': 1, 'list': [_atto(4690295, 'x', archiviazione='01/10/2026')]}
        with patch.object(link_resolver, 'lista_atti', return_value=listing):
            self.assertTrue(link_resolver.argo_archiviato(self.NUOVO))

    def test_non_archiviato(self):
        listing = {'totalRows': 1, 'list': [_atto(4690295, 'x', archiviazione='28/10/2026')]}
        with patch.object(link_resolver, 'lista_atti', return_value=listing):
            from datetime import date
            self.assertFalse(link_resolver.argo_archiviato(self.NUOVO, oggi=date(2026, 10, 15)))

    def test_assente_da_listing_completo_archiviato(self):
        with patch.object(link_resolver, 'lista_atti',
                          return_value={'totalRows': 1, 'list': [_atto(1, 'x')]}):
            self.assertTrue(link_resolver.argo_archiviato(self.NUOVO))

    def test_assente_da_listing_troncato_non_si_scarta(self):
        """Albo con più atti della pagina scaricata: l'assenza non prova nulla."""
        with patch.object(link_resolver, 'lista_atti',
                          return_value={'totalRows': 723, 'list': [_atto(1, 'x')]}):
            self.assertFalse(link_resolver.argo_archiviato(self.NUOVO))


if __name__ == '__main__':
    unittest.main()
