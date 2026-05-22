#!/bin/bash

# Script per eseguire il monitor interpelli
# Questo script può essere aggiunto al crontab per esecuzione automatica giornaliera

# Percorso dello script (modifica con il tuo percorso)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Log file
LOG_FILE="$SCRIPT_DIR/monitor.log"

# Esegui lo script Python e registra l'output
echo "=== Esecuzione $(date) ===" >> "$LOG_FILE"
python3 monitor_interpelli.py >> "$LOG_FILE" 2>&1
echo "" >> "$LOG_FILE"

# Mantieni solo gli ultimi 1000 righe del log per evitare che diventi troppo grande
tail -n 1000 "$LOG_FILE" > "$LOG_FILE.tmp" && mv "$LOG_FILE.tmp" "$LOG_FILE"
