#!/bin/bash
# Controllo di trasparenzascuole dal Mac: il WAF Cloudflare blocca gli IP di GitHub Actions.
# Lanciato da launchd ogni 30 minuti (tools/it.interpelli.trasparenzascuole.plist); solo
# questa sorgente, con config.json, stato e report propri nella cartella dati.
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATI="$HOME/Library/Application Support/interpelli-trasparenzascuole"
mkdir -p "$DATI"
cd "$DATI" || exit 1
# Primo avvio: parte dallo stato di GitHub per non rinotificare gli interpelli già inviati
[ -f interpelli_visti.json ] || cp "$REPO/interpelli_visti.json" .
echo "=== $(date) ==="
exec "$REPO/.venv/bin/python" "$REPO/monitor_interpelli.py" --source trasparenzascuole_albo
