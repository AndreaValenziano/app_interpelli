#!/usr/bin/env python3
"""
Script di test per verificare la configurazione del Monitor Interpelli BAT.
Usa la stessa logica di risoluzione credenziali di monitor_interpelli.py
(variabili d'ambiente > config.json > default).
"""

import json
import smtplib
import os
import sys
import argparse
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


def carica_config() -> dict:
    file_config = {}
    if os.path.exists('config.json'):
        with open('config.json', 'r', encoding='utf-8') as f:
            file_config = json.load(f)

    def get(key, default=''):
        return os.environ.get(key.upper()) or file_config.get(key) or default

    return {
        'email_mittente':     get('EMAIL_MITTENTE', 'tua_email@gmail.com'),
        'password_email':     get('PASSWORD_EMAIL', 'tua_password_app'),
        'email_destinatario': get('EMAIL_DESTINATARIO', 'destinatario@email.com'),
        'smtp_server':        get('SMTP_SERVER', 'smtp.gmail.com'),
        'smtp_port':          int(get('SMTP_PORT', '587')),
    }


def test_configurazione(invia_test: bool = False) -> bool:
    print("\n" + "="*60)
    print("TEST CONFIGURAZIONE MONITOR INTERPELLI BAT")
    print("="*60 + "\n")

    # 1. Carica configurazione
    print("1️⃣  Caricamento configurazione (env > config.json)...")
    config = carica_config()

    # 2. Verifica campi obbligatori
    print("\n2️⃣  Verifica campi configurazione...")
    campi = ['email_mittente', 'password_email', 'email_destinatario', 'smtp_server', 'smtp_port']
    for campo in campi:
        val = str(config.get(campo, ''))
        if not val:
            print(f"   ❌ Campo '{campo}' mancante")
            return False
        if 'tua_' in val.lower():
            print(f"   ⚠️  Campo '{campo}' contiene ancora il valore di esempio: {val}")
            return False
    print("   ✅ Tutti i campi sono presenti e configurati")
    print(f"   Mittente:     {config['email_mittente']}")
    print(f"   Destinatario: {config['email_destinatario']}")
    print(f"   SMTP:         {config['smtp_server']}:{config['smtp_port']}")

    # 3. Test connessione SMTP
    print("\n3️⃣  Test connessione SMTP...")
    try:
        server = smtplib.SMTP(config['smtp_server'], config['smtp_port'], timeout=10)
        server.starttls()
        print("   ✅ Connessione SMTP stabilita")
        server.login(config['email_mittente'], config['password_email'])
        print("   ✅ Login riuscito")
        server.quit()
    except smtplib.SMTPAuthenticationError:
        print("   ❌ Errore di autenticazione!")
        print("   💡 Se usi Gmail: verifica di usare una 'Password per le app'")
        print("      Guida: https://support.google.com/accounts/answer/185833")
        return False
    except Exception as e:
        print(f"   ❌ Errore nella connessione: {e}")
        return False

    # 4. Invio email di test (opzionale)
    if not invia_test and sys.stdin.isatty():
        risposta = input("\n4️⃣  Vuoi inviare un'email di test? (s/n): ").strip().lower()
        invia_test = risposta == 's'

    if invia_test:
        print("\n4️⃣  Invio email di test...")
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = '✅ Test Monitor Interpelli BAT - Funziona!'
            msg['From'] = config['email_mittente']
            msg['To'] = config['email_destinatario']

            html = """
            <html>
                <body style="font-family: Arial, sans-serif;">
                    <h2 style="color: #27ae60;">✅ Configurazione Corretta!</h2>
                    <p>Il tuo Monitor Interpelli BAT è configurato correttamente.</p>
                    <p>Riceverai notifiche per nuovi interpelli di primaria/infanzia (ADEE, ADAA, EEEE, AAAA).</p>
                    <p style="color: #7f8c8d; font-size: 12px; margin-top: 30px;">
                        Email di test generata da Monitor Interpelli BAT
                    </p>
                </body>
            </html>
            """
            msg.attach(MIMEText(html, 'html'))

            with smtplib.SMTP(config['smtp_server'], config['smtp_port']) as server:
                server.starttls()
                server.login(config['email_mittente'], config['password_email'])
                server.send_message(msg)

            print(f"   ✅ Email di test inviata a {config['email_destinatario']}")
        except Exception as e:
            print(f"   ❌ Errore nell'invio: {e}")
            return False

    print("\n" + "="*60)
    print("🎉 TUTTI I TEST SUPERATI!")
    print("="*60)
    print("\n✅ Il Monitor Interpelli BAT è pronto all'uso.")
    print("   Avvia con: python3 monitor_interpelli.py")
    print("   Test senza email: python3 monitor_interpelli.py --dry-run\n")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Verifica configurazione Monitor Interpelli BAT')
    parser.add_argument('--send-test', action='store_true', help='Invia email di test senza chiedere conferma')
    args = parser.parse_args()
    ok = test_configurazione(invia_test=args.send_test)
    sys.exit(0 if ok else 1)
