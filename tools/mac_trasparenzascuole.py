#!/usr/bin/env python3
"""Legge trasparenzascuole dal Mac (il WAF Cloudflare blocca GitHub Actions) e pubblica gli
interpelli in trasparenzascuole_mac.json su main, via API GitHub: la working copy non cambia.
Email, dedup e dashboard li fa il monitor su GitHub (sources/trasparenzascuole_mac.py).
Lanciato da launchd ogni 30 minuti (tools/it.interpelli.trasparenzascuole.plist)."""
import base64
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sources.trasparenzascuole_albo import TrasparenzascuoleAlboSource

PERCORSO = 'repos/AndreaValenziano/app_interpelli/contents/trasparenzascuole_mac.json'
# Senza novità il file si aggiorna solo ogni tanto, per dire al monitor che il Mac è vivo
ORE_BATTITO = 6


def _confrontabile(dati: dict) -> dict:
    # La data di rilevamento cambia a ogni lettura: non è una novità
    return {
        'errori': dati.get('errori', []),
        'interpelli': [{k: v for k, v in ip.items() if k != 'data_rilevamento'}
                       for ip in dati.get('interpelli', [])],
    }


def da_pubblicare(nuovi: dict, attuali: dict, adesso: datetime) -> bool:
    if _confrontabile(nuovi) != _confrontabile(attuali):
        return True
    try:
        return adesso - datetime.fromisoformat(attuali['aggiornato']) >= timedelta(hours=ORE_BATTITO)
    except (KeyError, ValueError):
        return True


def _gh(*args, stdin=None) -> str:
    return subprocess.run(['gh', 'api', *args], input=stdin, check=True,
                          capture_output=True, text=True).stdout


def main():
    source = TrasparenzascuoleAlboSource()
    interpelli = source.fetch()
    adesso = datetime.now()
    nuovi = {'aggiornato': adesso.isoformat(timespec='seconds'), 'errori': source.errori, 'interpelli': interpelli}

    try:
        corrente = json.loads(_gh(PERCORSO))
        sha, attuali = corrente['sha'], json.loads(base64.b64decode(corrente['content']))
    except subprocess.CalledProcessError as e:
        if 'Not Found' not in (e.stdout + e.stderr):
            raise
        sha, attuali = None, {}

    print(f"=== {adesso:%d/%m/%Y %H:%M}: {len(interpelli)} interpelli, {len(source.errori)} errori")
    if not da_pubblicare(nuovi, attuali, adesso):
        return
    testo = json.dumps(nuovi, ensure_ascii=False, indent=1) + '\n'
    corpo = {'message': 'chore: interpelli trasparenzascuole dal Mac [skip ci]',
             'content': base64.b64encode(testo.encode()).decode(), 'branch': 'main'}
    if sha:
        corpo['sha'] = sha
    _gh('-X', 'PUT', PERCORSO, '--input', '-', stdin=json.dumps(corpo))
    print("Pubblicato")


if __name__ == '__main__':
    main()
