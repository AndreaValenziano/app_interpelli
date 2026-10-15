import io
import json
import os
import smtplib
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

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

    def test_argo_nuovo_formato_dedupa_con_vecchio_nello_stato(self):
        """Lo stato storico contiene link Argo vecchio formato in minuscolo: lo stesso
        atto linkato da istruzionebat.it nel formato nuovo è già visto."""
        with open(self.tmp.name, 'w') as f:
            json.dump({'ids': [], 'links': [
                'https://www.portaleargo.it/albopretorio/online/#/dettaglio-atto'
                '?customercode=sc21815&id=4685557&archivio=false']}, f)
        nuovi, stato = self.monitor.filtra_nuovi_interpelli([_interpello(
            'x', link='https://www.portaleargo.it/albopretorio/online/#/SC21815/atti/4685557')])
        self.assertEqual(nuovi, [])
        self.assertIn('argo:SC21815:4685557', stato['links'])

    def test_argo_chiave_canonica_salvata_dedupa_alla_run_successiva(self):
        link = 'https://www.portaleargo.it/albopretorio/online/#/SC21815/atti/4690295'
        _, stato = self.monitor.filtra_nuovi_interpelli([_interpello('a', link=link)])
        self.monitor.save_interpelli_visti(stato)
        nuovi, _ = self.monitor.filtra_nuovi_interpelli([_interpello('b', link=link)])
        self.assertEqual(nuovi, [])

    def test_argo_due_formati_nella_stessa_run(self):
        nuovi, _ = self.monitor.filtra_nuovi_interpelli([
            _interpello('a', link='https://www.portaleargo.it/albopretorio/online/#/dettaglio-atto'
                                  '?customerCode=SC21815&id=4690295&archivio=false'),
            _interpello('b', link='https://www.portaleargo.it/albopretorio/online/#/SC21815/atti/4690295'),
        ])
        self.assertEqual([ip['stable_id'] for ip in nuovi], ['a'])


class TestInviaEmail(unittest.TestCase):
    """invia_email deve dire in quale fase SMTP fallisce: il 28/09/2026 una password
    per le app revocata (535) ha bloccato le notifiche per 17 giorni senza che il
    log lo rendesse evidente."""

    def setUp(self):
        self.monitor = InterpelliMonitor(config_file='/nonexistent.json', dry_run=False)

    def _invia(self, smtp_mock):
        out = io.StringIO()
        with patch('monitor_interpelli.smtplib.SMTP', smtp_mock), redirect_stdout(out):
            ok = self.monitor.invia_email([_interpello('a')])
        return ok, out.getvalue()

    def _server(self, smtp_mock):
        return smtp_mock.return_value.__enter__.return_value

    def test_successo(self):
        smtp = MagicMock()
        ok, _ = self._invia(smtp)
        self.assertTrue(ok)
        self._server(smtp).send_message.assert_called_once()
        self.assertIn('timeout', smtp.call_args.kwargs)

    def test_credenziali_rifiutate_suggerisce_rigenerare_password(self):
        smtp = MagicMock()
        self._server(smtp).login.side_effect = smtplib.SMTPAuthenticationError(
            535, b'5.7.8 Username and Password not accepted')
        ok, out = self._invia(smtp)
        self.assertFalse(ok)
        self.assertIn('login', out)
        self.assertIn('SMTPAuthenticationError', out)
        self.assertIn('PASSWORD_EMAIL', out)

    def test_connessione_chiusa_indica_fase(self):
        smtp = MagicMock()
        self._server(smtp).starttls.side_effect = smtplib.SMTPServerDisconnected(
            'Connection unexpectedly closed')
        ok, out = self._invia(smtp)
        self.assertFalse(ok)
        self.assertIn('starttls', out)
        self.assertIn('SMTPServerDisconnected', out)
        self.assertNotIn('PASSWORD_EMAIL', out)

    def test_errore_di_connessione(self):
        smtp = MagicMock(side_effect=OSError('Network is unreachable'))
        ok, out = self._invia(smtp)
        self.assertFalse(ok)
        self.assertIn('connessione', out)


class TestEseguiInvioFallito(unittest.TestCase):

    def setUp(self):
        self.cwd = os.getcwd()
        self.tmp = tempfile.TemporaryDirectory()
        os.chdir(self.tmp.name)

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def test_stato_non_salvato_ed_exit_1(self):
        """Con SMTP rotto lo stato resta intatto (la run successiva ritenta) e il
        processo esce con 1, così il workflow non committa interpelli_visti.json."""
        sorgente = MagicMock()
        sorgente.name = 'test'
        sorgente.fetch.return_value = [_interpello('a', scadenza='31/12/2099')]
        monitor = InterpelliMonitor(config_file='/nonexistent.json', dry_run=False)
        with patch('monitor_interpelli.get_enabled_sources', return_value=[sorgente]), \
             patch('monitor_interpelli.in_fascia_invio', return_value=True), \
             patch.object(monitor, 'invia_email', return_value=False), \
             patch('monitor_interpelli.aggiorna_dashboard'), \
             redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                monitor.esegui()
        self.assertEqual(ctx.exception.code, 1)
        self.assertFalse(os.path.exists('interpelli_visti.json'))


class TestErroriSorgenti(unittest.TestCase):
    """Le sorgenti rotte restituivano [] con un print: argo_albo è rimasta cieca per
    settimane senza che nessuno se ne accorgesse."""

    def setUp(self):
        self.cwd = os.getcwd()
        self.tmp = tempfile.TemporaryDirectory()
        os.chdir(self.tmp.name)

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def _esegui(self, env):
        sorgente = MagicMock()
        sorgente.name = 'argo_albo'
        sorgente.fetch.return_value = [_interpello('a', scadenza='31/12/2099')]
        sorgente.errori = ['Errore per SC21815: risposta Argo inattesa']
        monitor = InterpelliMonitor(config_file='/nonexistent.json', dry_run=True)
        out = io.StringIO()
        with patch('monitor_interpelli.get_enabled_sources', return_value=[sorgente]), \
             patch.dict(os.environ, env, clear=False), \
             patch('monitor_interpelli.aggiorna_dashboard'), \
             redirect_stdout(out):
            monitor.esegui()
        return monitor, out.getvalue()

    def test_annotazione_workflow_su_github_actions(self):
        _, out = self._esegui({'GITHUB_ACTIONS': 'true'})
        self.assertIn('::warning title=Sorgente argo_albo::Errore per SC21815', out)

    def test_report_elenca_sorgenti_con_problemi(self):
        self._esegui({})
        [md] = [f for f in os.listdir('reports') if f.endswith('.md') and f.startswith('run-')]
        with open(os.path.join('reports', md), encoding='utf-8') as f:
            contenuto = f.read()
        self.assertIn('Sorgenti con problemi', contenuto)
        self.assertIn('risposta Argo inattesa', contenuto)

    def test_email_riporta_sorgenti_con_problemi(self):
        monitor, _ = self._esegui({})
        html = monitor.crea_email_html([_interpello('a')])
        self.assertIn('argo_albo', html)
        self.assertIn('risposta Argo inattesa', html)


class TestDettagli(unittest.TestCase):
    """Ora di scadenza, periodo, ore settimanali e sede, dal PDF o dal testo."""

    PDF = ("per 24 ore settimanali • dal 19/10/2026 al 30/06/2027 • presso la sede di "
           "servizio: “De Amicis” – Minervino Murge La domanda da far pervenire entro e non "
           "oltre le ore 1 2:00 del 15/10/2026")

    def setUp(self):
        self.monitor = InterpelliMonitor(config_file='/nonexistent.json', dry_run=True)

    def test_dettagli_dal_documento_risolto(self):
        ip = _interpello('a', link='https://scuola.example/x/')
        with patch('monitor_interpelli.risolvi_da_link', return_value=('15/10/2026', self.PDF)):
            self.monitor.risolvi_scadenze([ip])
        self.monitor.aggiungi_dettagli([ip])
        self.assertEqual(ip['scadenza'], '15/10/2026')
        self.assertEqual(ip['dettagli'], {
            'ora_scadenza': '12:00', 'periodo': 'dal 19/10/2026 al 30/06/2027',
            'ore': '24 h/sett', 'sede': '“De Amicis” – Minervino Murge'})

    def test_dettagli_dal_testo_se_manca_il_documento(self):
        ip = _interpello('a')
        ip['testo'] = 'Interpello ADEE supplenza dal 01/10/2026 al 30/11/2026'
        self.monitor.aggiungi_dettagli([ip])
        self.assertEqual(ip['dettagli'], {'periodo': 'dal 01/10/2026 al 30/11/2026'})

    def test_email_mostra_i_dettagli(self):
        ip = _interpello('a', scadenza='15/10/2026')
        ip['dettagli'] = {'ora_scadenza': '12:00', 'periodo': 'dal 19/10/2026 al 30/06/2027',
                          'ore': '24 h/sett', 'sede': '“De Amicis” – Minervino Murge'}
        html = self.monitor.crea_email_html([ip])
        self.assertIn('15/10/2026 ore 12:00', html)
        self.assertIn('dal 19/10/2026 al 30/06/2027', html)
        self.assertIn('24 h/sett', html)
        self.assertIn('De Amicis', html)


class TestFasciaOraria(unittest.TestCase):
    """Niente email di notte: si invia solo dalle 8 alle 22 ora italiana, con ora
    legale e solare (il cron GitHub è in UTC, il trigger esterno può avere ritardi)."""

    def _ora(self, s):
        from datetime import datetime, timezone
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)

    def test_estate(self):
        from monitor_interpelli import in_fascia_invio
        self.assertFalse(in_fascia_invio(self._ora('2026-07-01T05:59')))  # 07:59 CEST
        self.assertTrue(in_fascia_invio(self._ora('2026-07-01T06:00')))   # 08:00 CEST
        self.assertTrue(in_fascia_invio(self._ora('2026-07-01T19:59')))   # 21:59 CEST
        self.assertFalse(in_fascia_invio(self._ora('2026-07-01T20:00')))  # 22:00 CEST

    def test_inverno(self):
        from monitor_interpelli import in_fascia_invio
        self.assertFalse(in_fascia_invio(self._ora('2026-12-01T06:59')))  # 07:59 CET
        self.assertTrue(in_fascia_invio(self._ora('2026-12-01T07:00')))   # 08:00 CET
        self.assertFalse(in_fascia_invio(self._ora('2026-12-01T21:00')))  # 22:00 CET

    def test_fuori_fascia_nessuna_azione(self):
        sorgente = MagicMock()
        sorgente.name = 'test'
        monitor = InterpelliMonitor(config_file='/nonexistent.json', dry_run=False)
        with patch('monitor_interpelli.get_enabled_sources', return_value=[sorgente]), \
             patch('monitor_interpelli.in_fascia_invio', return_value=False), \
             patch.object(monitor, 'invia_email') as invia, \
             patch.object(monitor, 'save_interpelli_visti') as salva, \
             redirect_stdout(io.StringIO()):
            monitor.esegui()
        sorgente.fetch.assert_not_called()
        invia.assert_not_called()
        salva.assert_not_called()


if __name__ == '__main__':
    unittest.main()
