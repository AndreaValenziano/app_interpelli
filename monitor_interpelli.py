#!/usr/bin/env python3
"""
Monitor Interpelli BAT - Supplenze Primaria e Infanzia
Monitora gli interpelli per sostegno e posto comune su scuola primaria e infanzia nella provincia BAT
Classi di concorso monitorate: ADEE, ADAA, EEEE, AAAA
"""

import json
import smtplib
import os
import sys
import argparse
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import date, datetime, timedelta
from html import escape as html_escape
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import List, Dict, Optional

from sources import get_enabled_sources
from filtering import (
    CODICI_OBIETTIVO, chiave_link, estrai_dettagli, is_link_dedupabile, normalizza_codici,
    parse_data, scadenza_passata, supplenza_gia_iniziata,
)
from link_resolver import argo_archiviato, link_specifico_argo, risolvi_da_link
from reporting import RunReporter, prune_old_reports
from dashboard import GIORNI_IGNOTA_ATTIVA, aggiorna_dashboard, carica_archivio

# Cap alle risoluzioni scadenza via HTTP per run (protegge da reset dello stato)
MAX_RISOLUZIONI_LINK = 40

# Secondi di attesa massima per ogni operazione SMTP (senza, un server muto blocca la run)
SMTP_TIMEOUT = 30


# Le email si inviano solo in questa fascia (ora italiana, estremi [inizio, fine)):
# fuori fascia il run non fa nulla e gli interpelli arrivano col primo run del mattino
ORA_INIZIO_INVIO = 8
ORA_FINE_INVIO = 22
FUSO_ORARIO = ZoneInfo('Europe/Rome')


def in_fascia_invio(adesso: Optional[datetime] = None) -> bool:
    ora = (adesso or datetime.now(FUSO_ORARIO)).astimezone(FUSO_ORARIO).hour
    return ORA_INIZIO_INVIO <= ora < ORA_FINE_INVIO


# Riverifica dell'archivio dashboard: record senza scadenza riprovati per run
MAX_RIVERIFICHE = 10
# Finestra di pubblicazione dell'atto Argo cercato per un link generico senza data
GIORNI_RICERCA_ATTO = 10


def _codici(testo: str) -> List[str]:
    testo = normalizza_codici(testo or '').upper()
    return [c for c in CODICI_OBIETTIVO if c in testo]


def _html_dettagli(dettagli: Dict) -> str:
    """Riga con periodo, ore settimanali e sede (solo quelli trovati)."""
    voci = [(icona, dettagli.get(k)) for icona, k in
            (('🗓', 'periodo'), ('⌛', 'ore'), ('📍', 'sede'))]
    voci = [f"{icona} {html_escape(v)}" for icona, v in voci if v]
    return f'<p class="dettagli">{" · ".join(voci)}</p>' if voci else ''


def _label_scadenza(scadenza: str, ora: str = '', dettagli: Optional[Dict] = None) -> str:
    """Etichetta leggibile con indicazione di urgenza per l'email."""
    d = parse_data(scadenza)
    if d is None:
        inizio = supplenza_gia_iniziata(dettagli or {})
        if inizio:
            return (f"⚠️ non rilevata — supplenza iniziata il {inizio.strftime('%d/%m/%Y')}: "
                    f"probabilmente già chiuso, verifica dal link")
        return '⚠️ non rilevata — apri il link e verifica subito'
    giorni = (d - datetime.now().date()).days
    if ora:
        scadenza = f"{scadenza} ore {ora}"
    if giorni <= 0:
        return f'<strong style="color:#c0392b">{scadenza} — SCADE OGGI!</strong>'
    if giorni == 1:
        return f'<strong style="color:#c0392b">{scadenza} — scade domani</strong>'
    return f'{scadenza} (tra {giorni} giorni)'


class InterpelliMonitor:
    def __init__(self, config_file='config.json', dry_run=False, source_filter=None):
        self.config_file = config_file
        self.dry_run = dry_run
        self.source_filter = source_filter
        self.config = self.load_config()
        self.interpelli_salvati = "interpelli_visti.json"
        self.problemi_sorgenti: Dict[str, List[str]] = {}

    def load_config(self) -> Dict:
        file_config = {}
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r', encoding='utf-8') as f:
                file_config = json.load(f)

        # Env vars (GitHub Secrets) hanno precedenza su config.json
        def get(key, default=''):
            return os.environ.get(key.upper()) or file_config.get(key) or default

        return {
            'email_mittente':     get('EMAIL_MITTENTE', 'tua_email@gmail.com'),
            'password_email':     get('PASSWORD_EMAIL', 'tua_password_app'),
            'email_destinatario': get('EMAIL_DESTINATARIO', 'destinatario@email.com'),
            'smtp_server':        get('SMTP_SERVER', 'smtp.gmail.com'),
            'smtp_port':          int(get('SMTP_PORT', '587')),
        }

    def save_config(self):
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(self.config, indent=4, ensure_ascii=False, fp=f)

    def load_interpelli_visti(self) -> Dict:
        vuoto = {"ids": [], "links": []}
        if not os.path.exists(self.interpelli_salvati):
            return vuoto
        with open(self.interpelli_salvati, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # Gestisce il vecchio formato lista (migrazione)
        if isinstance(data, list):
            return vuoto
        return data

    def save_interpelli_visti(self, stato: Dict):
        with open(self.interpelli_salvati, 'w', encoding='utf-8') as f:
            json.dump(stato, indent=4, ensure_ascii=False, fp=f)

    def filtra_nuovi_interpelli(self, interpelli: List[Dict], reporter=None):
        """Dedup cross-sorgente. Ritorna (nuovi, stato_aggiornato) SENZA salvare:
        lo stato va salvato solo dopo l'invio email riuscito, altrimenti un errore
        SMTP marcherebbe come 'visti' interpelli mai notificati."""
        stato = self.load_interpelli_visti()
        seen_ids = set(stato.get("ids", []))
        # Chiavi canoniche: anche i link storici (minuscoli, Argo vecchio formato)
        # vengono convertiti, così i due formati di deep-link Argo dedupano tra loro
        seen_links = {chiave_link(l) or l for l in stato.get("links", [])}
        nuovi = []

        for interpello in interpelli:
            sid = interpello['stable_id']
            # I link generici (homepage scuola, albo intero) sono condivisi da più
            # interpelli: usarli per il dedup sopprimerebbe quelli successivi.
            link = chiave_link(interpello.get('link') or '')

            # Salta se già visto per contenuto O per link (dedup cross-sorgente)
            if sid in seen_ids or (link and link in seen_links):
                if reporter:
                    reporter.record_already_seen(interpello)
                continue

            nuovi.append(interpello)
            seen_ids.add(sid)
            if link:
                seen_links.add(link)

        return nuovi, {"ids": list(seen_ids), "links": list(seen_links)}

    def risolvi_scadenze(self, interpelli: List[Dict]):
        """Per gli interpelli senza scadenza, segue il link e cerca la data nella
        pagina di dettaglio e negli allegati PDF. Solo sui NUOVI (costa HTTP)."""
        da_risolvere = [ip for ip in interpelli if not ip.get('scadenza') and ip.get('link')]
        if not da_risolvere:
            return
        print(f"🔎 Risoluzione scadenze via link/PDF per {len(da_risolvere)} interpelli...")
        for ip in da_risolvere[:MAX_RISOLUZIONI_LINK]:
            scad, testo = risolvi_da_link(ip['link'])
            if scad:
                ip['scadenza'] = scad
                ip['testo_documento'] = testo
                print(f"   ✓ {scad} ← {ip['title'][:70]}")

    def aggiungi_dettagli(self, interpelli: List[Dict]):
        """Ora di scadenza, periodo, ore settimanali e sede: dal documento letto (PDF o
        pagina) e, per ciò che manca, dal testo dell'interpello. Nessuna richiesta HTTP."""
        for ip in interpelli:
            scad = ip.get('scadenza', '')
            ip['dettagli'] = {**estrai_dettagli(ip.get('testo', ''), scad),
                              **estrai_dettagli(ip.get('testo_documento', ''), scad)}

    def riconduci_link_generici(self, interpelli: List[Dict]):
        """Link alla homepage di una scuola Argo → deep-link dell'atto (stesso codice,
        pubblicato quel giorno o negli ultimi giorni). Così la scadenza si trova e
        l'interpello deduplica con quello di argo_albo."""
        for ip in interpelli:
            link = ip.get('link') or ''
            if not link or is_link_dedupabile(link):
                continue
            pubblicato = parse_data(ip.get('data_pubblicazione', ''))
            dal, al = ((pubblicato - timedelta(days=1), pubblicato + timedelta(days=1)) if pubblicato
                       else (date.today() - timedelta(days=GIORNI_RICERCA_ATTO), date.today()))
            specifico = link_specifico_argo(link, _codici(ip.get('testo', '')), dal, al)
            if specifico:
                print(f"   🔗 {link} → {specifico}")
                ip['link'] = specifico

    def riverifica_archivio(self) -> List[Dict]:
        """Riprova sui record recenti della dashboard ancora senza scadenza: link generico
        → atto Argo, scadenza da link/PDF, atto archiviato. Ritorna i record aggiornati
        (da passare ad aggiorna_dashboard). Nessuna email."""
        limite = datetime.now() - timedelta(days=GIORNI_IGNOTA_ATTIVA)
        da_rivedere = []
        for r in carica_archivio():
            try:
                rilevato = datetime.fromisoformat(r.get('data_rilevamento', ''))
            except ValueError:
                continue
            if not r.get('scadenza') and not r.get('archiviato') and r.get('link') and rilevato >= limite:
                da_rivedere.append((r, rilevato.date()))
        aggiornati = []
        for r, rilevato in da_rivedere[:MAX_RIVERIFICHE]:
            link = r['link']
            if not is_link_dedupabile(link):
                link = link_specifico_argo(link, _codici(r.get('testo', '')),
                                           rilevato - timedelta(days=GIORNI_RICERCA_ATTO), rilevato) or link
            scadenza, testo = risolvi_da_link(link)
            archiviato = not scadenza and argo_archiviato(link)
            if scadenza or archiviato or link != r['link']:
                aggiornato = dict(r, link=link, scadenza=scadenza or '', archiviato=archiviato,
                                  dettagli={**estrai_dettagli(r.get('testo', ''), scadenza),
                                            **estrai_dettagli(testo, scadenza)})
                aggiornati.append(aggiornato)
                print(f"   ♻️  {r.get('title', '')[:60]} → "
                      f"{scadenza or ('archiviato' if archiviato else link)}")
        return aggiornati

    def crea_email_html(self, interpelli: List[Dict]) -> str:
        html = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; }}
                h2 {{ color: #2c3e50; }}
                .interpello {{
                    background-color: #f8f9fa;
                    border-left: 4px solid #3498db;
                    padding: 15px;
                    margin: 10px 0;
                }}
                .tipo {{ color: #e74c3c; font-weight: bold; }}
                .scadenza {{ color: #f39c12; }}
                .dettagli {{ color: #2c3e50; }}
                .fonte {{ color: #95a5a6; font-size: 11px; }}
                .link {{ color: #3498db; }}
                .footer {{
                    margin-top: 30px;
                    padding-top: 20px;
                    border-top: 1px solid #ddd;
                    color: #7f8c8d;
                    font-size: 12px;
                }}
            </style>
        </head>
        <body>
            <h2>🔔 Nuovi Interpelli Primaria/Infanzia - Provincia BAT</h2>
            <p><strong>Data:</strong> {datetime.now().strftime('%d/%m/%Y %H:%M')}</p>
            <p><strong>Totale nuovi interpelli:</strong> {len(interpelli)}</p>
            <p><em>Classi di concorso monitorate: ADEE, ADAA, EEEE, AAAA</em></p>
            <hr>
        """

        for i, interpello in enumerate(interpelli, 1):
            dettagli = interpello.get('dettagli') or {}
            html += f"""
            <div class="interpello">
                <h3>Interpello #{i}</h3>
                <p class="tipo">📋 Tipo: {interpello['tipo']}</p>
                <p class="scadenza">📅 Scadenza domanda: {_label_scadenza(interpello['scadenza'], dettagli.get('ora_scadenza', ''), dettagli)}</p>
                {_html_dettagli(dettagli)}
                <p class="fonte">Fonte: {interpello['source']}</p>
                <p><strong>Descrizione:</strong><br>{interpello['testo'][:300]}...</p>
            """
            if interpello.get('link'):
                html += f'<p class="link">🔗 <a href="{interpello["link"]}">Vai all\'interpello</a></p>'
            html += "</div>"

        html += f"""
            <div class="footer">{self._html_problemi_sorgenti()}
                <p>Questa email è stata generata automaticamente dal Monitor Interpelli BAT.</p>
                <p>Controlla sempre il sito ufficiale: <a href="https://www.istruzionebat.it">istruzionebat.it</a></p>
            </div>
        </body>
        </html>
        """
        return html

    def _html_problemi_sorgenti(self) -> str:
        if not self.problemi_sorgenti:
            return ''
        voci = ''.join(f"<li><strong>{html_escape(nome)}</strong>: {html_escape('; '.join(errori))[:300]}</li>"
                       for nome, errori in self.problemi_sorgenti.items())
        return (f"<p>⚠️ Sorgenti con problemi in questa esecuzione "
                f"(possibili interpelli non rilevati):</p><ul>{voci}</ul>")

    def _oggetto_email(self, interpelli: List[Dict]) -> str:
        n = len(interpelli)
        oggetto = f'🔔 {n} Nuov{"o" if n == 1 else "i"} Interpell{"o" if n == 1 else "i"} Primaria/Infanzia BAT'
        scadenze = sorted(d for d in (parse_data(ip['scadenza']) for ip in interpelli) if d)
        if scadenze:
            oggetto += f' — scadenza più vicina {scadenze[0].strftime("%d/%m")}'
        return oggetto

    def invia_email(self, interpelli: List[Dict]) -> bool:
        """Invia la notifica. Ritorna True se l'invio è riuscito (o dry-run)."""
        if not interpelli:
            print("Nessun nuovo interpello da inviare.")
            return True

        if self.dry_run:
            print(f"\n[DRY-RUN] Email NON inviata. Oggetto: {self._oggetto_email(interpelli)}")
            for i, ip in enumerate(interpelli, 1):
                print(f"  [{i}] [{ip['source']}] {ip['title'][:80]}")
                print(f"       Tipo: {ip['tipo']} | Scadenza: {ip['scadenza'] or 'Non specificata'}")
                print(f"       Link: {ip.get('link') or '—'}")
                if ip.get('dettagli'):
                    print(f"       Dettagli: {ip['dettagli']}")
            return True

        n = len(interpelli)
        msg = MIMEMultipart('alternative')
        msg['Subject'] = self._oggetto_email(interpelli)
        msg['From'] = self.config['email_mittente']
        msg['To'] = self.config['email_destinatario']
        msg.attach(MIMEText(self.crea_email_html(interpelli), 'html'))

        # La fase in cui cade l'invio distingue le cause (rete, TLS, credenziali)
        fase = 'connessione'
        try:
            with smtplib.SMTP(self.config['smtp_server'], self.config['smtp_port'],
                              timeout=SMTP_TIMEOUT) as server:
                fase = 'starttls'
                server.starttls()
                fase = 'login'
                server.login(self.config['email_mittente'], self.config['password_email'])
                fase = 'invio'
                server.send_message(msg)
        except Exception as e:
            print(f"❌ Errore SMTP in fase '{fase}' ({type(e).__name__}): {e}")
            if isinstance(e, smtplib.SMTPAuthenticationError):
                # Google revoca le password per le app (es. cambio password account):
                # senza questo suggerimento il 535 si confonde con un guasto di rete
                print("   ↳ Credenziali rifiutate: la password per le app Gmail è probabilmente "
                      "stata revocata. Generane una nuova su "
                      "https://myaccount.google.com/apppasswords e aggiorna il secret PASSWORD_EMAIL.")
            return False

        print(f"✅ Email inviata con successo! ({n} interpell{'o' if n == 1 else 'i'})")
        return True

    def esegui(self):
        print(f"\n{'='*60}")
        print(f"Monitor Interpelli BAT - {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        if self.dry_run:
            print("  [MODALITÀ DRY-RUN — nessuna email, nessun salvataggio stato]")
        print(f"{'='*60}\n")

        # Fuori fascia nessuna azione: niente email di notte, e lo stato resta com'è
        # così gli interpelli trovati arrivano col primo run in fascia
        if not self.dry_run and not in_fascia_invio():
            print(f"🌙 Fuori dalla fascia di invio ({ORA_INIZIO_INVIO}-{ORA_FINE_INVIO} ora italiana): "
                  f"nessuna esecuzione.")
            return

        reporter = RunReporter()

        sources = get_enabled_sources()
        if self.source_filter:
            sources = [s for s in sources if s.name == self.source_filter]
            if not sources:
                print(f"❌ Sorgente '{self.source_filter}' non trovata. Sorgenti disponibili: "
                      f"{', '.join(s.name for s in get_enabled_sources())}")
                sys.exit(1)

        tutti = []
        for source in sources:
            print(f"🔍 [{source.name}] Recupero interpelli...")
            risultati = source.fetch(reporter=reporter)
            print(f"   Trovati {len(risultati)} interpelli corrispondenti ai codici obiettivo")
            tutti.extend(risultati)
            errori = list(getattr(source, 'errori', None) or [])
            if errori:
                self.problemi_sorgenti[source.name] = errori
                reporter.record_source_errors(source.name, errori)

        # Sorgenti rotte: annotazioni visibili nella pagina della run, senza far
        # fallire il job (trasparenzascuole è bloccata dal WAF su ogni run CI)
        if self.problemi_sorgenti:
            print(f"\n⚠️  Sorgenti con problemi: {', '.join(self.problemi_sorgenti)}")
            if os.environ.get('GITHUB_ACTIONS') == 'true':
                for nome, errori in self.problemi_sorgenti.items():
                    for e in errori:
                        print(f"::warning title=Sorgente {nome}::{e}")

        print(f"\n📊 Totale grezzo (da tutte le sorgenti): {len(tutti)}")
        self.riconduci_link_generici(tutti)
        scaduti = [ip for ip in tutti if scadenza_passata(ip.get('scadenza', ''))]
        for ip in scaduti:
            reporter.record_expired(ip)
        tutti = [ip for ip in tutti if not scadenza_passata(ip.get('scadenza', ''))]
        n_scaduti = len(scaduti)
        if n_scaduti:
            print(f"⏰ Scartati {n_scaduti} interpell{'o' if n_scaduti == 1 else 'i'} scadut{'o' if n_scaduti == 1 else 'i'}")

        print("🆕 Filtro nuovi interpelli (dedup cross-sorgente)...")
        nuovi, stato_nuovo = self.filtra_nuovi_interpelli(tutti, reporter=reporter)
        print(f"✨ Trovati {len(nuovi)} nuovi interpelli")

        # Risoluzione scadenze via link/PDF SOLO sui nuovi (costa richieste HTTP)
        self.risolvi_scadenze(nuovi)
        self.aggiungi_dettagli(nuovi)

        # Ri-controllo dopo la risoluzione: le scadenze appena scoperte possono
        # essere già passate. Restano comunque nello stato (non vanno rinotificati).
        def _morto(ip):
            if scadenza_passata(ip.get('scadenza', '')):
                return True
            # Senza scadenza rilevabile: se è un atto Argo non più in pubblicazione
            # (sparito dall'albo o con dataArchiviazione passata) è certamente inutile
            return not ip.get('scadenza') and argo_archiviato(ip.get('link') or '')

        scaduti_post = [ip for ip in nuovi if _morto(ip)]
        for ip in scaduti_post:
            reporter.record_expired(ip)
        nuovi = [ip for ip in nuovi if ip not in scaduti_post]
        if scaduti_post:
            print(f"⏰ Scartati {len(scaduti_post)} già scaduti/archiviati (scoperto da PDF/albo)")

        # Ordina per urgenza: scadenza più vicina prima, senza scadenza in fondo
        nuovi.sort(key=lambda ip: (parse_data(ip.get('scadenza', '')) is None,
                                   parse_data(ip.get('scadenza', '')) or datetime.max.date()))
        for ip in nuovi:
            reporter.record_notified(ip)

        if nuovi:
            print("📧 Invio email in corso...")
            invio_ok = self.invia_email(nuovi)
        else:
            print("ℹ️  Nessun nuovo interpello da notificare.")
            invio_ok = True

        # Lo stato si salva solo se la notifica è andata a buon fine: in caso di
        # errore SMTP la prossima run ritenta con gli stessi interpelli.
        if invio_ok and not self.dry_run:
            self.save_interpelli_visti(stato_nuovo)

        aggiornati = [] if self.dry_run else self.riverifica_archivio()
        aggiorna_dashboard(nuovi + aggiornati, dry_run=self.dry_run)

        reports_dir = Path('reports')
        json_path, md_path = reporter.write(reports_dir)
        prune_old_reports(reports_dir)
        print(f"📝 Report: {md_path}")

        print(f"\n{'='*60}\n")

        if not invio_ok:
            sys.exit(1)


def _credenziali_ok(config: Dict) -> bool:
    required = ['email_mittente', 'password_email', 'email_destinatario']
    return all(config.get(k) and 'tua_' not in str(config.get(k, '')).lower() for k in required)


def main():
    parser = argparse.ArgumentParser(description='Monitor Interpelli BAT - Supplenze Primaria/Infanzia')
    parser.add_argument('--dry-run', action='store_true',
                        help='Esegui senza inviare email né salvare lo stato (per test)')
    parser.add_argument('--source', metavar='NAME',
                        help='Limita a una sola sorgente, es. istruzionebat_rss')
    args = parser.parse_args()

    monitor = InterpelliMonitor(dry_run=args.dry_run, source_filter=args.source)

    if not _credenziali_ok(monitor.config):
        if sys.stdin.isatty() and not args.dry_run:
            print("⚙️  Prima esecuzione - Configurazione necessaria\n")
            print("NOTA: Per Gmail, usa una 'Password per le app' invece della password normale")
            print("Guida: https://support.google.com/accounts/answer/185833\n")
            monitor.config['email_mittente'] = input("Email mittente (Gmail consigliato): ").strip()
            monitor.config['password_email'] = input("Password app (o password email): ").strip()
            monitor.config['email_destinatario'] = input("Email destinatario: ").strip()
            monitor.save_config()
            print("\n✅ Configurazione salvata!\n")
        elif not args.dry_run:
            print("❌ Credenziali email non configurate.")
            print("   Imposta le variabili d'ambiente EMAIL_MITTENTE, PASSWORD_EMAIL, EMAIL_DESTINATARIO")
            print("   oppure compila config.json (vedi config.json.example).")
            sys.exit(1)

    monitor.esegui()


if __name__ == "__main__":
    main()
