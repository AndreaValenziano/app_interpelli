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
from filtering import scadenza_passata
from reporting import RunReporter, prune_old_reports


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

    def filtra_nuovi_interpelli(self, interpelli: List[Dict], reporter=None) -> List[Dict]:
        stato = self.load_interpelli_visti()
        seen_ids = set(stato.get("ids", []))
        seen_links = set(stato.get("links", []))
        nuovi = []

        for interpello in interpelli:
            sid = interpello['stable_id']
            link = (interpello.get('link') or '').strip().lower()

            # Salta se già visto per contenuto O per link (dedup cross-sorgente)
            if sid in seen_ids or (link and link in seen_links):
                if reporter:
                    reporter.record_already_seen(interpello)
                continue

            nuovi.append(interpello)
            seen_ids.add(sid)
            if link:
                seen_links.add(link)
            if reporter:
                reporter.record_notified(interpello)

        if not self.dry_run:
            self.save_interpelli_visti({"ids": list(seen_ids), "links": list(seen_links)})

        return nuovi

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
                <p class="scadenza">📅 Scadenza: {interpello['scadenza'] or 'Non specificata'}</p>
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

    def invia_email(self, interpelli: List[Dict]):
        if not interpelli:
            print("Nessun nuovo interpello da inviare.")
            return

        if self.dry_run:
            n = len(interpelli)
            print(f"\n[DRY-RUN] Email NON inviata. Oggetto: 🔔 {n} Nuov{'o' if n == 1 else 'i'} Interpell{'o' if n == 1 else 'i'} Primaria/Infanzia BAT")
            for i, ip in enumerate(interpelli, 1):
                print(f"  [{i}] [{ip['source']}] {ip['title'][:80]}")
                print(f"       Tipo: {ip['tipo']} | Scadenza: {ip['scadenza'] or 'Non specificata'}")
                print(f"       Link: {ip.get('link') or '—'}")
            return

        try:
            n = len(interpelli)
            msg = MIMEMultipart('alternative')
            msg['Subject'] = f'🔔 {n} Nuov{"o" if n == 1 else "i"} Interpell{"o" if n == 1 else "i"} Primaria/Infanzia BAT'
            msg['From'] = self.config['email_mittente']
            msg['To'] = self.config['email_destinatario']
            msg.attach(MIMEText(self.crea_email_html(interpelli), 'html'))

            with smtplib.SMTP(self.config['smtp_server'], self.config['smtp_port']) as server:
                server.starttls()
                server.login(self.config['email_mittente'], self.config['password_email'])
                server.send_message(msg)

            print(f"✅ Email inviata con successo! ({n} interpell{'o' if n == 1 else 'i'})")
        except Exception as e:
            print(f"❌ Errore nell'invio dell'email: {e}")

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
        n_pre = len(tutti)
        scaduti = [ip for ip in tutti if scadenza_passata(ip.get('scadenza', ''))]
        for ip in scaduti:
            reporter.record_expired(ip)
        tutti = [ip for ip in tutti if not scadenza_passata(ip.get('scadenza', ''))]
        n_scaduti = len(scaduti)
        if n_scaduti:
            print(f"⏰ Scartati {n_scaduti} interpell{'o' if n_scaduti == 1 else 'i'} scadut{'o' if n_scaduti == 1 else 'i'}")
        print("🆕 Filtro nuovi interpelli (dedup cross-sorgente)...")
        nuovi = self.filtra_nuovi_interpelli(tutti, reporter=reporter)
        print(f"✨ Trovati {len(nuovi)} nuovi interpelli")

        if nuovi:
            print("📧 Invio email in corso...")
            self.invia_email(nuovi)
        else:
            print("ℹ️  Nessun nuovo interpello da notificare.")

        reports_dir = Path('reports')
        json_path, md_path = reporter.write(reports_dir)
        prune_old_reports(reports_dir)
        print(f"📝 Report: {md_path}")

        print(f"\n{'='*60}\n")


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
