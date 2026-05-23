import sys
import os
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from filtering import estrai_scadenza, scadenza_passata


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
