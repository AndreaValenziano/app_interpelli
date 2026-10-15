import sys
import os
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from filtering import (
    estrai_scadenza,
    scadenza_passata,
    is_sostegno_primaria_infanzia,
    is_link_dedupabile,
    chiave_link,
    identifica_tipo_interpello,
)


class TestEstraiScadenzaQualificata(unittest.TestCase):
    """Testi che contengono la scadenza domanda in forma qualificata — devono restituire la data."""

    def test_ore_del_giorno(self):
        testo = "Gli aspiranti sono invitati ad inviare la propria disponibilità entro le ore 13.00 del giorno 13/05/2026"
        self.assertEqual(estrai_scadenza(testo), "13/05/2026")

    def test_ore_del_giorno_con_punto(self):
        testo = "entro le ore 13.00 del giorno 13.05.2026"
        self.assertEqual(estrai_scadenza(testo), "13/05/2026")

    def test_ore_senza_entro(self):
        testo = "Il conferimento sarà comunicato entro le ore 20.00 del 13/05/2026"
        self.assertEqual(estrai_scadenza(testo), "13/05/2026")

    def test_entro_e_non_oltre_ore(self):
        testo = "Entro e non oltre le ore 14:00 del giorno 18.05.2026"
        self.assertEqual(estrai_scadenza(testo), "18/05/2026")

    def test_scadenza_domanda_con_due_punti(self):
        testo = "Scadenza presentazione domanda: 18/05/2026"
        self.assertEqual(estrai_scadenza(testo), "18/05/2026")

    def test_termine_domande(self):
        testo = "Termine presentazione domande 18-05-2026"
        self.assertEqual(estrai_scadenza(testo), "18/05/2026")

    def test_candidatura_entro(self):
        testo = "Presentare la candidatura entro il 18/05/2026"
        self.assertEqual(estrai_scadenza(testo), "18/05/2026")

    def test_manifestazione_interesse(self):
        testo = "Manifestazione di interesse entro il 18/05/2026"
        self.assertEqual(estrai_scadenza(testo), "18/05/2026")

    def test_termine_perentorio(self):
        testo = "Entro il termine perentorio del 18/05/2026"
        self.assertEqual(estrai_scadenza(testo), "18/05/2026")

    def test_domanda_entro(self):
        testo = "La domanda dovrà pervenire entro le ore 12:00 del 18/05/2026"
        self.assertEqual(estrai_scadenza(testo), "18/05/2026")

    def test_presentazione_domanda(self):
        testo = "Presentazione della domanda: 18/05/2026"
        self.assertEqual(estrai_scadenza(testo), "18/05/2026")

    def test_disponibilita_entro(self):
        testo = "inviare la propria disponibilità entro le ore 13.00 del 13/05/2026"
        self.assertEqual(estrai_scadenza(testo), "13/05/2026")


class TestEstraiScadenzaContratto(unittest.TestCase):
    """Testi che contengono solo date di contratto — devono restituire stringa vuota."""

    def test_supplenza_breve_al(self):
        testo = "Interpello per n.1 supplenza breve al 24.05.2026 posto comune scuola primaria"
        self.assertEqual(estrai_scadenza(testo), "")

    def test_dal_al_contratto(self):
        testo = "supplenza breve sc. primaria posto sostegno 24h sett. dal 11.05.2026 al 09.06.2026"
        self.assertEqual(estrai_scadenza(testo), "")

    def test_nomina_dal_al(self):
        testo = "Nomina dal 15/05/2026 al 30/06/2026"
        self.assertEqual(estrai_scadenza(testo), "")

    def test_incarico_fino_al(self):
        testo = "Incarico fino al 30/06/2026"
        self.assertEqual(estrai_scadenza(testo), "")

    def test_nome_file_con_date_contratto(self):
        testo = "timbro_atto_individuazione_N01_24h_sett._cdc.ADEE_da11.05.a09.06.2026.pdf"
        self.assertEqual(estrai_scadenza(testo), "")

    def test_periodo_supplenza(self):
        testo = "Periodo della supplenza: dalla presa di servizio al 24/05/2026"
        self.assertEqual(estrai_scadenza(testo), "")


class TestEstraiScadenzaMisto(unittest.TestCase):
    """Testi con entrambe le date — la scadenza domanda deve vincere."""

    def test_domanda_vince_su_contratto(self):
        testo = (
            "Supplenza dal 20/05/2026 al 30/06/2026. "
            "Le domande dovranno pervenire entro le ore 12:00 del 18/05/2026."
        )
        self.assertEqual(estrai_scadenza(testo), "18/05/2026")

    def test_pdf_interpello_reale(self):
        # Replica del testo estratto da un PDF Argo reale (interpello EEEE Bisceglie 2026)
        testo = (
            "Tipologia di posto: Comune Scuola Primaria "
            "Periodo della supplenza: dalla presa di servizio al 24/05/2026 "
            "Gli aspiranti interessati sono invitati ad inviare la propria disponibilità "
            "entro le ore 13.00 del giorno 13/05/2026 mediante il portale madinterpello.portaleargo.it"
        )
        self.assertEqual(estrai_scadenza(testo), "13/05/2026")


class TestEstraiScadenzaEdge(unittest.TestCase):
    """Casi limite."""

    def test_testo_vuoto(self):
        self.assertEqual(estrai_scadenza(""), "")

    def test_solo_data_senza_contesto(self):
        self.assertEqual(estrai_scadenza("18/05/2026"), "")

    def test_data_separatore_trattino(self):
        testo = "Le domande entro le ore 12:00 del 18-05-2026"
        self.assertEqual(estrai_scadenza(testo), "18/05/2026")

    def test_spazi_multipli_normalizzati(self):
        testo = "domanda   dovrà   pervenire  entro  il  18/05/2026"
        self.assertEqual(estrai_scadenza(testo), "18/05/2026")


class TestEstraiScadenzaFormatiEstesi(unittest.TestCase):
    """Formati data aggiunti: mese testuale, giorno a 1 cifra, giorno della settimana, ore con virgola."""

    def test_mese_testuale(self):
        testo = "entro le ore 12:00 del giorno 3 dicembre 2025"
        self.assertEqual(estrai_scadenza(testo), "03/12/2025")

    def test_mese_testuale_con_ordinale(self):
        testo = "la domanda dovrà pervenire entro il 1° luglio 2026"
        self.assertEqual(estrai_scadenza(testo), "01/07/2026")

    def test_giorno_una_cifra(self):
        testo = "entro le ore 12:00 del 3/9/2026"
        self.assertEqual(estrai_scadenza(testo), "03/09/2026")

    def test_giorno_settimana(self):
        testo = "entro le ore 10:00 del giorno venerdì 12/09/2026"
        self.assertEqual(estrai_scadenza(testo), "12/09/2026")

    def test_ore_con_virgola(self):
        testo = "entro le ore 12,00 del 18/05/2026"
        self.assertEqual(estrai_scadenza(testo), "18/05/2026")

    def test_data_invalida_scartata(self):
        testo = "entro le ore 12:00 del 45/13/2026"
        self.assertEqual(estrai_scadenza(testo), "")


class TestFiltroAllargato(unittest.TestCase):
    """Il filtro deve riconoscere anche vecchi codici (EH/CH) e keyword senza codici."""

    def test_codice_gps(self):
        self.assertTrue(is_sostegno_primaria_infanzia("interpello ADEE 24h"))

    def test_vecchio_codice_eh(self):
        self.assertTrue(is_sostegno_primaria_infanzia(
            "Interpello nazionale scuola primaria posto sostegno EH"))

    def test_vecchio_codice_ch(self):
        self.assertTrue(is_sostegno_primaria_infanzia(
            "Interpello per supplenza posto sostegno CH scuola dell'infanzia"))

    def test_keyword_senza_codice(self):
        self.assertTrue(is_sostegno_primaria_infanzia(
            "interpello per supplenza scuola infanzia posto comune"))

    def test_ch_minuscolo_non_match(self):
        # 'ch' dentro parole comuni non deve attivare il vecchio codice
        self.assertFalse(is_sostegno_primaria_infanzia(
            "interpello per docente di chimica scuola secondaria sostegno"))

    def test_dsga_escluso(self):
        self.assertFalse(is_sostegno_primaria_infanzia(
            "interpello per incarico di DSGA sostituzione"))

    def test_graduatoria_esclusa_da_fallback(self):
        self.assertFalse(is_sostegno_primaria_infanzia(
            "graduatoria interpello scuola primaria sostegno"))


class TestLinkDedupabile(unittest.TestCase):
    """I link generici (condivisi da più interpelli) non vanno usati per il dedup."""

    def test_argo_senza_id_generico(self):
        self.assertFalse(is_link_dedupabile(
            "https://www.portaleargo.it/albopretorio/online/#/?customerCode=SC27220"))

    def test_argo_deep_link_ok(self):
        self.assertTrue(is_link_dedupabile(
            "https://www.portaleargo.it/albopretorio/online/#/dettaglio-atto?customerCode=SC29432&id=4416677&archivio=false"))

    def test_trasparenza_senza_fragment_generico(self):
        self.assertFalse(is_link_dedupabile(
            "https://www.trasparenzascuole.it/Public/APDPublic_ExtV2.aspx?CF=90091020728"))

    def test_trasparenza_con_fragment_ok(self):
        self.assertTrue(is_link_dedupabile(
            "https://www.trasparenzascuole.it/Public/APDPublic_ExtV2.aspx?CF=90091020728#atto-abc"))

    def test_homepage_scuola_generica(self):
        self.assertFalse(is_link_dedupabile("https://www.icjannuzzimonsdidonna.edu.it"))

    def test_pagina_articolo_ok(self):
        self.assertTrue(is_link_dedupabile("https://www.istruzionebat.it/2025/12/02/interpello-x/"))

    def test_vuoto(self):
        self.assertFalse(is_link_dedupabile(""))


class TestLinkArgoNuovoFormato(unittest.TestCase):
    """Dal 2026 istruzionebat.it e scuolainterpelli.it linkano gli atti Argo come
    '#/SC21815/atti/ID' invece di '#/dettaglio-atto?customerCode=..&id=..': i due
    formati devono dedupare tra loro (stesso atto da sorgenti diverse)."""

    NUOVO = "https://www.portaleargo.it/albopretorio/online/#/SC21815/atti/4690295"
    VECCHIO = ("https://www.portaleargo.it/albopretorio/online/#/dettaglio-atto"
               "?customerCode=SC21815&id=4690295&archivio=false")

    def test_nuovo_formato_dedupabile(self):
        self.assertTrue(is_link_dedupabile(self.NUOVO))

    def test_albo_senza_atto_nel_nuovo_formato_generico(self):
        self.assertFalse(is_link_dedupabile(
            "https://www.portaleargo.it/albopretorio/online/#/SC21815/atti"))

    def test_chiave_canonica_uguale_per_i_due_formati(self):
        self.assertEqual(chiave_link(self.NUOVO), 'argo:SC21815:4690295')
        self.assertEqual(chiave_link(self.VECCHIO), 'argo:SC21815:4690295')

    def test_chiave_da_link_gia_minuscolo(self):
        # lo stato storico salva i link in minuscolo
        self.assertEqual(chiave_link(self.VECCHIO.lower()), 'argo:SC21815:4690295')

    def test_chiave_gia_canonica_resta_invariata(self):
        # lo stato salva le chiavi canoniche e le rilegge con chiave_link
        self.assertEqual(chiave_link('argo:SC21815:4690295'), 'argo:SC21815:4690295')

    def test_chiave_link_generico_vuota(self):
        self.assertEqual(chiave_link("https://www.icminervinomurge.edu.it/"), '')

    def test_chiave_link_normale_minuscola(self):
        self.assertEqual(chiave_link(" https://www.IstruzioneBat.it/2026/x/ "),
                         'https://www.istruzionebat.it/2026/x/')


class TestCodiciSpezzati(unittest.TestCase):
    """istruzionebat.it pubblica titoli con codici spezzati da spazi ('E EEE',
    'B B 0 2'): l'EEEE del 13/10/2026 (Pietrocola) è stato perso per questo."""

    def test_e_eee(self):
        self.assertTrue(is_sostegno_primaria_infanzia(
            "Interpello nazionale per supplenza docente su classe di concorso E EEE – Posto Comune"))

    def test_ee_ee(self):
        self.assertTrue(is_sostegno_primaria_infanzia("supplenza classe di concorso EE EE"))

    def test_ad_ee(self):
        self.assertTrue(is_sostegno_primaria_infanzia("classe di concorso AD EE sostegno"))

    def test_tipo_con_codice_spezzato(self):
        self.assertEqual(identifica_tipo_interpello("classe di concorso E EEE"),
                         'POSTO COMUNE PRIMARIA (EEEE)')

    def test_codice_non_target_spezzato_resta_escluso(self):
        self.assertFalse(is_sostegno_primaria_infanzia(
            "Interpello classe di concorso B B 0 2 CONVERSAZIONE IN LINGUA"))

    def test_lettere_in_parole_non_diventano_codici(self):
        self.assertFalse(is_sostegno_primaria_infanzia("A ADA E AEE graduatoria"))


class TestEsitiEVerbaliEsclusi(unittest.TestCase):
    """Verbali, esiti e atti di individuazione/nomina chiudono un interpello: non
    sono candidabili anche se contengono il codice o 'primaria sostegno'."""

    def test_verbale_operazioni(self):
        self.assertFalse(is_sostegno_primaria_infanzia(
            "VERBALE DELLE OPERAZIONI PER L'INDIVIDUAZIONE DI N.1 DOCENTE DI SOSTEGNO "
            "DI SCUOLA PRIMARIA (INTERPELLO DEL 05/10/2026)"))

    def test_esito_con_codice(self):
        self.assertFalse(is_sostegno_primaria_infanzia("Esito interpello ADEE del 05/10/2026"))

    def test_individuazione_da_interpello(self):
        self.assertFalse(is_sostegno_primaria_infanzia(
            "Individuazione da interpello per supplenza breve cl. di concorso ADEE fino al 01.04.2026"))

    def test_atto_di_nomina(self):
        self.assertFalse(is_sostegno_primaria_infanzia(
            "ATTO DI NOMINA CONTRATTO A T.D. DOCENTE SOSTEGNO SCUOLA PRIMARIA"))

    def test_interpello_per_individuazione_resta_valido(self):
        # 'individuazione' da sola compare anche negli avvisi veri
        self.assertTrue(is_sostegno_primaria_infanzia(
            "Interpello per l'individuazione di un docente ADEE"))


class TestScadenzaPassata(unittest.TestCase):
    """scadenza_passata() deve usare solo date qualificate già estratte."""

    OGGI = date(2026, 5, 23)

    def test_scaduta(self):
        self.assertTrue(scadenza_passata("18/05/2026", oggi=self.OGGI))

    def test_non_scaduta(self):
        self.assertFalse(scadenza_passata("30/06/2026", oggi=self.OGGI))

    def test_vuota_non_scarta(self):
        self.assertFalse(scadenza_passata("", oggi=self.OGGI))

    def test_non_parsabile_non_scarta(self):
        self.assertFalse(scadenza_passata("Non specificata", oggi=self.OGGI))


if __name__ == '__main__':
    unittest.main()
