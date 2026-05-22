# Monitor Interpelli BAT - Supplenze Primaria e Infanzia

Programma Python per monitorare automaticamente gli interpelli per supplenze su scuola primaria e infanzia (sostegno e posto comune) nella provincia di Barletta-Andria-Trani (BAT).

## 📋 Caratteristiche

- ✅ Monitora il sito ufficiale dell'Ufficio Scolastico BAT
- ✅ Filtra automaticamente interpelli per:
    - **ADEE** - Sostegno scuola primaria
    - **ADAA** - Sostegno scuola infanzia
    - **EEEE** - Posto comune scuola primaria
    - **AAAA** - Posto comune scuola infanzia
- ✅ Invia notifiche email solo per nuovi interpelli
- ✅ Evita duplicati grazie al tracciamento degli interpelli già visti
- ✅ Estrae informazioni chiave (tipo, scadenza, link)
- ✅ Email HTML formattate e facilmente leggibili

## 🚀 Installazione

### 1. Requisiti
- Python 3.7 o superiore
- Account email (Gmail consigliato)

### 2. Installa le dipendenze

```bash
pip install -r requirements.txt
```

Oppure manualmente:
```bash
pip install requests beautifulsoup4 lxml
```

### 3. Configurazione Email

#### Per Gmail (consigliato):

1. Vai su https://myaccount.google.com/security
2. Attiva la verifica in due passaggi
3. Vai su https://myaccount.google.com/apppasswords
4. Crea una "Password per le app" per "Mail"
5. Usa questa password nel programma (NON la tua password normale)

#### Per altri provider:
- **Outlook/Hotmail**: smtp.office365.com, porta 587
- **Yahoo**: smtp.mail.yahoo.com, porta 587
- **Libero**: smtp.libero.it, porta 587

## 📝 Primo Utilizzo

### Esecuzione iniziale

```bash
python3 monitor_interpelli.py
```

Al primo avvio, il programma ti chiederà:
1. **Email mittente**: la tua email (es. tuaemail@gmail.com)
2. **Password**: la password per le app (se Gmail) o password normale
3. **Email destinatario**: dove ricevere le notifiche

Queste informazioni verranno salvate in `config.json` e non dovrai reinserirle.

## 🔄 Esecuzione Automatica Giornaliera

### Opzione 1: Cron (Linux/Mac)

1. Rendi eseguibile lo script bash:
```bash
chmod +x esegui_monitor.sh
```

2. Apri il crontab:
```bash
crontab -e
```

3. Aggiungi una riga per l'esecuzione giornaliera (es. alle 8:00):
```bash
0 8 * * * /percorso/completo/esegui_monitor.sh
```

Esempi di scheduling:
- `0 8 * * *` - Ogni giorno alle 8:00
- `0 8,14,20 * * *` - Tre volte al giorno: 8:00, 14:00, 20:00
- `0 */4 * * *` - Ogni 4 ore

### Opzione 2: Utilità di Pianificazione (Windows)

1. Apri "Utilità di Pianificazione"
2. Crea un'attività base
3. Trigger: Giornaliera, ora desiderata
4. Azione: Avvia programma
5. Programma: `python`
6. Argomenti: `percorso\completo\monitor_interpelli.py`
7. Inizia in: `percorso\della\cartella`

### Opzione 3: Esecuzione Manuale

Semplicemente esegui:
```bash
python3 monitor_interpelli.py
```

## 📁 File Generati

- **config.json**: Configurazione email (non condividere!)
- **interpelli_visti.json**: Elenco interpelli già notificati
- **monitor.log**: Log delle esecuzioni (se usi lo script bash)

## 🔧 Configurazione Avanzata

### Modifica manuale della configurazione

Modifica il file `config.json`:

```json
{
    "email_mittente": "tua_email@gmail.com",
    "password_email": "tua_password_app",
    "email_destinatario": "destinatario@email.com",
    "smtp_server": "smtp.gmail.com",
    "smtp_port": 587
}
```

### Reset interpelli visti

Per ricevere nuovamente notifiche per tutti gli interpelli:
```bash
rm interpelli_visti.json
```

## 🎯 Cosa Monitora

Il programma cerca interpelli che contengono:
- **ADEE**: Sostegno scuola primaria
- **ADAA**: Sostegno scuola infanzia
- **EEEE**: Posto comune scuola primaria
- **AAAA**: Posto comune scuola infanzia

Fonte dati: https://www.istruzionebat.it/interpelli/a-s-2025-2026/

## 📧 Formato Email

Le email contengono:
- 🔔 Numero di nuovi interpelli
- 📋 Tipo di interpello (ADEE/ADAA/EEEE/AAAA)
- 📅 Scadenza (se disponibile)
- 📝 Descrizione completa
- 🔗 Link diretto all'interpello

## ❓ Risoluzione Problemi

### Errore "Authentication failed"
- Controlla che stai usando la "Password per le app" (Gmail)
- Verifica che l'email e password siano corrette
- Controlla che l'accesso SMTP sia abilitato

### Nessun interpello trovato
- Il sito potrebbe essere temporaneamente non disponibile
- Controlla manualmente il sito per verificare

### Email non ricevute
- Controlla la cartella spam
- Verifica che l'email destinatario sia corretta
- Controlla i log in `monitor.log`

## 🔒 Sicurezza

⚠️ **IMPORTANTE**:
- NON condividere il file `config.json` (contiene la tua password)
- Usa sempre "Password per le app" per Gmail
- Mantieni privato il file con le credenziali

## 📊 Statistiche

Il programma mostrerà:
```
🔍 Recupero interpelli in corso...
📊 Trovati X interpelli per primaria/infanzia (totali)
🆕 Filtro nuovi interpelli...
✨ Trovati Y nuovi interpelli
📧 Invio email in corso...
✅ Email inviata con successo! (Y interpelli)
```

## 🆘 Supporto

Per problemi o domande:
1. Verifica di aver seguito tutti i passaggi
2. Controlla il file `monitor.log`
3. Controlla manualmente il sito: https://www.istruzionebat.it/interpelli/a-s-2025-2026/

## 📜 Licenza

Questo programma è fornito "così com'è" per uso personale.

## ⚠️ Disclaimer

Questo è un monitor automatico non ufficiale. Controlla sempre il sito ufficiale dell'Ufficio Scolastico per confermare le informazioni e le scadenze degli interpelli.

---

**Buon lavoro e in bocca al lupo per le supplenze! 🍀**
