"""Test del resolver di scadenze (rete mockata)."""
import unittest
from unittest.mock import patch

import link_resolver
from link_resolver import risolvi_da_link, risolvi_scadenza_da_link


PDF_CON_SCADENZA = b'%PDF-FINTO'

# Pagina in stile "Design Scuole Italia" (siti .edu.it): la sezione allegati
# sta FUORI dal <main> — caso reale icverdicafaro.edu.it, ottobre 2025.
PAGINA_ALLEGATI_FUORI_MAIN = b"""
<html><body>
<main class="main-container">
  <h1>Interpello nazionale ADEE</h1>
  <p>interpello da Direttore amministrativo</p>
</main>
<section class="allegati">
  <a href="https://scuola.example/wp-content/uploads/2025/10/interpello-adee.pdf">
    Allegato per interpello ADEE
  </a>
</section>
</body></html>
"""


class TestAllegatiFuoriContenuto(unittest.TestCase):
    def setUp(self):
        link_resolver._cache.clear()

    def test_pdf_fuori_dal_main_viene_trovato(self):
        def fake_scarica(url):
            if url.endswith('.pdf'):
                return PDF_CON_SCADENZA, 'application/pdf'
            return PAGINA_ALLEGATI_FUORI_MAIN, 'text/html'

        with patch.object(link_resolver, '_scarica', side_effect=fake_scarica), \
             patch.object(link_resolver, '_testo_da_pdf_bytes',
                          return_value='domanda entro le ore 12:00 del 29/10/2025'):
            self.assertEqual(risolvi_scadenza_da_link('https://scuola.example/interpello-adee/'),
                             '29/10/2025')

    def test_scadenza_nel_testo_fuori_dal_main(self):
        pagina = (b'<html><body><main><p>Interpello ADEE</p></main>'
                  b'<footer><p>domanda entro il 15/09/2026</p></footer>'
                  b'</body></html>')
        with patch.object(link_resolver, '_scarica',
                          return_value=(pagina, 'text/html')):
            self.assertEqual(risolvi_scadenza_da_link('https://scuola.example/x/'), '15/09/2026')

    def test_restituisce_anche_il_testo_per_i_dettagli(self):
        pagina = (b'<html><body><main><p>Interpello ADEE per 12 ore settimanali, '
                  b'domanda entro le ore 10:00 del 15/09/2026</p></main></body></html>')
        with patch.object(link_resolver, '_scarica', return_value=(pagina, 'text/html')):
            scadenza, testo = risolvi_da_link('https://scuola.example/y/')
        self.assertEqual(scadenza, '15/09/2026')
        self.assertIn('12 ore settimanali', testo)


if __name__ == '__main__':
    unittest.main()
