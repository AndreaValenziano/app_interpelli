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
from datetime import datetime
from pathlib import Path
from typing import List, Dict

from sources import get_enabled_sources
from filtering import scadenza_passata, is_link_dedupabile, parse_data
from link_resolver import risolvi_scadenza_da_link
from reporting import RunReporter, prune_old_reports
from dashboard import aggiorna_dashboard

# Cap alle risoluzioni scadenza via HTTP per run (protegge da reset dello stato)
MAX_RISOLUZIONI_LINK = 40


def _label_scadenza(scadenza: str) -> str:
    """Etichetta leggibile con indicazione di urgenza per l'email."""
    d = parse_data(scadenza)
    if d is None:
        return '⚠️ non rilevata — apri il link e verifica subito'
    giorni = (d - datetime.now().date()).days
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
        seen_links = set(stato.get("links", []))
        nuovi = []

        for interpello in interpelli:
            sid = interpello['stable_id']
            link_raw = interpello.get('link') or ''
            # I link generici (homepage scuola, albo intero) sono condivisi da più
            # interpelli: usarli per il dedup sopprimerebbe quelli successivi.
            link = link_raw.strip().lower() if is_link_dedupabile(link_raw) else ''

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
            scad = risolvi_scadenza_da_link(ip['link'])
            if scad:
                ip['scadenza'] = scad
                print(f"   ✓ {scad} ← {ip['title'][:70]}")

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
            html += f"""
            <div class="interpello">
                <h3>Interpello #{i}</h3>
                <p class="tipo">📋 Tipo: {interpello['tipo']}</p>
                <p class="scadenza">📅 Scadenza domanda: {_label_scadenza(interpello['scadenza'])}</p>
                <p class="fonte">Fonte: {interpello['source']}</p>
                <p><strong>Descrizione:</strong><br>{interpello['testo'][:300]}...</p>
            """
            if interpello.get('link'):
                html += f'<p class="link">🔗 <a href="{interpello["link"]}">Vai all\'interpello</a></p>'
            html += "</div>"

        html += """
            <div class="footer">
                <p>Questa email è stata generata automaticamente dal Monitor Interpelli BAT.</p>
                <p>Controlla sempre il sito ufficiale: <a href="https://www.istruzionebat.it">istruzionebat.it</a></p>
            </div>
        </body>
        </html>
        """
        return html

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
            return True

        try:
            n = len(interpelli)
            msg = MIMEMultipart('alternative')
            msg['Subject'] = self._oggetto_email(interpelli)
            msg['From'] = self.config['email_mittente']
            msg['To'] = self.config['email_destinatario']
            msg.attach(MIMEText(self.crea_email_html(interpelli), 'html'))

            with smtplib.SMTP(self.config['smtp_server'], self.config['smtp_port']) as server:
                server.starttls()
                server.login(self.config['email_mittente'], self.config['password_email'])
                server.send_message(msg)

            print(f"✅ Email inviata con successo! ({n} interpell{'o' if n == 1 else 'i'})")
            return True
        except Exception as e:
            print(f"❌ Errore nell'invio dell'email: {e}")
            return False

    def esegui(self):
        print(f"\n{'='*60}")
        print(f"Monitor Interpelli BAT - {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        if self.dry_run:
            print("  [MODALITÀ DRY-RUN — nessuna email, nessun salvataggio stato]")
        print(f"{'='*60}\n")

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

        print(f"\n📊 Totale grezzo (da tutte le sorgenti): {len(tutti)}")
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

        # Ri-controllo dopo la risoluzione: le scadenze appena scoperte possono
        # essere già passate. Restano comunque nello stato (non vanno rinotificati).
        scaduti_post = [ip for ip in nuovi if scadenza_passata(ip.get('scadenza', ''))]
        for ip in scaduti_post:
            reporter.record_expired(ip)
        nuovi = [ip for ip in nuovi if not scadenza_passata(ip.get('scadenza', ''))]
        if scaduti_post:
            print(f"⏰ Scartati {len(scaduti_post)} già scaduti (scadenza scoperta dal PDF)")

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

        aggiorna_dashboard(nuovi, dry_run=self.dry_run)

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
