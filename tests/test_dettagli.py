"""Test di estrai_dettagli: ora di scadenza, periodo, ore settimanali, sede.
Testi presi dai PDF reali degli interpelli Argo (ottobre 2026), estratti con pypdf."""
import unittest

from datetime import date

from filtering import estrai_dettagli, inizio_supplenza

PIETROCOLA = (
    "per il conferimento di n. 1 supplenza • per 24 ore settimanali • dal 19/10/2026 al "
    "30/06/2027 • presso la sede di servizio: “De Amicis” – Minervino Murge La domanda da far "
    "pervenire entro e non oltre le ore 1 2:00 del 15/10/2026 dovrà contenere tutte le "
    "dichiarazioni. I dati saranno trattati dal Titolare in conformità al GDPR.")

SPINAZZOLA = (
    "conferimento di n. 1 supplenza • per 05 ore settimanali • dal 28/09/2026 al 30/06/2027 • "
    "giorno di servizio – LUNEDI’ • presso la sede di servizio: “FERMI” – Spinazzola La domanda "
    "da far pervenire entro e non oltre le ore 09:00 del 26/09/2026 dovrà contenere")


class TestEstraiDettagli(unittest.TestCase):

    def test_avviso_completo(self):
        self.assertEqual(estrai_dettagli(PIETROCOLA, '15/10/2026'), {
            'ora_scadenza': '12:00',
            'periodo': 'dal 19/10/2026 al 30/06/2027',
            'ore': '24 h/sett',
            'sede': '“De Amicis” – Minervino Murge',
        })

    def test_ore_con_zero_iniziale_e_voce_extra(self):
        d = estrai_dettagli(SPINAZZOLA, '26/09/2026')
        self.assertEqual(d['ora_scadenza'], '09:00')
        self.assertEqual(d['ore'], '5 h/sett')
        self.assertEqual(d['sede'], '“FERMI” – Spinazzola')

    def test_ora_di_altra_data_ignorata(self):
        testo = "colloquio alle ore 10:00 del 20/10/2026. Domande entro il 15/10/2026"
        self.assertNotIn('ora_scadenza', estrai_dettagli(testo, '15/10/2026'))

    def test_ora_dopo_la_data(self):
        testo = "La domanda va inviata entro il 15/10/2026 alle ore 13.30 via PEC"
        self.assertEqual(estrai_dettagli(testo, '15/10/2026')['ora_scadenza'], '13:30')

    def test_fino_al(self):
        self.assertEqual(estrai_dettagli("supplenza fino al 30.06.2027 per 12 ore")['periodo'],
                         'fino al 30/06/2027')

    def test_fino_avente_diritto(self):
        self.assertEqual(estrai_dettagli("supplenza fino all’avente diritto")['periodo'],
                         "fino all'avente diritto")

    def test_titolo_istruzionebat(self):
        d = estrai_dettagli("SCUOLA PRIMARIA ADEE SOSTEGNO – supplenza breve e saltuaria "
                            "dal 01/10/2026 al 30/11/2026")
        self.assertEqual(d, {'periodo': 'dal 01/10/2026 al 30/11/2026'})

    def test_testo_vuoto(self):
        self.assertEqual(estrai_dettagli(''), {})


class TestInizioSupplenza(unittest.TestCase):

    def test_dal_al(self):
        self.assertEqual(inizio_supplenza({'periodo': 'dal 01/10/2026 al 30/11/2026'}), date(2026, 10, 1))

    def test_fino_al_o_vuoto(self):
        self.assertIsNone(inizio_supplenza({'periodo': 'fino al 30/06/2027'}))
        self.assertIsNone(inizio_supplenza({}))


if __name__ == '__main__':
    unittest.main()
