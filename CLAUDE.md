# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Monitor Interpelli BAT** is a Python automation tool that monitors substitute teaching job postings (interpelli) across multiple sources for the Barletta-Andria-Trani (BAT) province in Italy, filters them for target classes (ADEE, ADAA, EEEE, AAAA — sostegno + posto comune, primaria/infanzia), and sends HTML email notifications for new postings. It runs unattended via GitHub Actions.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Dry-run: fetch all sources, print results — no email, no state written (idempotent)
python3 monitor_interpelli.py --dry-run

# Dry-run limited to one source (for debugging a specific fetcher)
python3 monitor_interpelli.py --dry-run --source istruzionebat_rss

# Real run (uses stored config or env vars for email)
python3 monitor_interpelli.py

# Validate SMTP credentials and optionally send a test email
python3 test_configurazione.py
python3 test_configurazione.py --send-test   # no interactive prompt

# Reset deduplication state (re-notify all current postings on next run)
rm interpelli_visti.json
```

## Architecture

### Module layout

```
monitor_interpelli.py   # orchestrator + email + dedup + expiry filter
filtering.py            # shared filter logic (codici, dedup ID, date extraction, expiry)
pdf_utils.py            # deadline extraction from PDF via pypdf (in-memory cache)
sources/
  __init__.py           # get_enabled_sources() registry
  base.py               # BaseSource ABC + shared _http_get()
  istruzionebat_rss.py  # primary: UST BAT WordPress RSS feed
  istruzionebat_html.py # fallback: scrape the HTML index page
  scuolainterpelli_rss.py  # secondary: national aggregator, filtered for BAT
  argo_albo.py          # per-school: queries Argo albo pretorio API
.github/workflows/monitor.yml  # GitHub Actions cron scheduler
```

### Data flow

1. `esegui()` iterates `get_enabled_sources()` → each `fetch()` returns normalized posting dicts already filtered by target codes.
2. `esegui()` discards expired postings using `scadenza_passata()` (logs "⏰ Scartati N scaduti"). Postings with no parseable deadline are kept (better a false positive than a miss).
3. `filtra_nuovi_interpelli()` deduplicates: skips if `stable_id` (sha256 of normalized text) OR normalized link already seen. Writes updated state to `interpelli_visti.json` (unless `--dry-run`).
4. `invia_email()` sends HTML via SMTP+STARTTLS.

### Normalized posting dict fields

Each fetcher returns dicts with: `testo`, `title`, `link`, `tipo`, `scadenza`, `source`, `stable_id`, `data_rilevamento`. `scadenza` is `'DD/MM/YYYY'` or `''` (never `'Non specificata'` — callers display that label for empty string).

### Filtering functions (`filtering.py`)

- `is_sostegno_primaria_infanzia`, `identifica_tipo_interpello`: keyword matching on ADEE/ADAA/EEEE/AAAA.
- `estrai_scadenza(testo)`: recognizes separators `.`/`/`/`-` and keywords (al/entro il/scadenza/termine/fino al/dal…al). Returns `'DD/MM/YYYY'` or `''`.
- `parse_data(s)`: parses `'DD/MM/YYYY'` → `date`. Returns `None` on failure.
- `scadenza_passata(s, oggi=None)`: `True` only if parseable AND < today. Non-parseable → `False` (do not discard).
- `compute_stable_id(testo)`: `hashlib.sha256` (not Python's `hash()`, which is salted per-process and would break dedup across GitHub Actions runs).

### Deadline resolution per source (fallback chain)

Each fetcher populates `scadenza` with the first non-empty result:
1. `estrai_scadenza(testo)` — title + description + allegato filenames.
2. If link ends in `.pdf` → `estrai_scadenza_da_pdf(link)` (pdf_utils).
- **Argo** additionally falls back to `dataArchiviazione` (albo archiving date) as last resort — this is *not* the application deadline but is better than nothing. Priority: `estrai_scadenza(testo) or dataArchiviazione`.

### Sources

- **`istruzionebat_rss`** (primary): `feedparser` on `istruzionebat.it/category/interpello/feed/`. Each RSS entry is one interpello. Simple, robust.
- **`istruzionebat_html`** (fallback): BeautifulSoup on the HTML index page. URL hardcoded for the school year — update `URL` in `sources/istruzionebat_html.py` annually.
- **`scuolainterpelli_rss`** (secondary): `feedparser` on `scuolainterpelli.it/feed/`. The RSS `content:encoded` is a big HTML blob organized by region (`<h2>`) → province subheading (`Interpelli pubblicati da: <strong>NAME</strong>`) → entries. The source client-filters for PUGLIA region and BAT province keywords (`BAT_PROVINCE_KEYWORDS` constant). No server-side filter exists. May link to the general BAT page rather than specific interpelli.

- **`argo_albo`** (Phase 2 — per-school): POST to `portaleargo.it/albopretorio/api/public/atti/filters/{customerCode}` for each BAT school in `scuole_bat.json`. Filters to category "C2 - Interpelli", excludes graduatorie. Matches ADEE/ADAA/EEEE/AAAA in both `descrizione` AND allegato filenames (codes often appear only in the PDF name). `stable_id` is based on `argo-{customerCode}-{attoId}` (not text hash) for robustness. Requires `scuole_bat.json` with `customerCode` entries — if file missing, returns `[]` silently.

Adding a new source: create a subclass of `BaseSource` in `sources/`, implement `fetch()`, register it in `sources/__init__.py:get_enabled_sources()`.

### Persistent files

| File | Purpose |
|---|---|
| `config.json` | SMTP credentials (never commit — in `.gitignore`) |
| `interpelli_visti.json` | `{"ids": [...sha256...], "links": [...urls...]}` for seen postings |
| `scuole_bat.json` | BAT school list with Argo `customerCode`; generated by `build_scuole_bat.py` |
| `monitor.log` | Append-only log by `esegui_monitor.sh` (in `.gitignore`) |

Old format of `interpelli_visti.json` was a bare `[]` list — `load_interpelli_visti()` migrates it to the new format automatically on first run.

### Credentials resolution (env > config.json > default)

`load_config()` reads: `EMAIL_MITTENTE`, `PASSWORD_EMAIL`, `EMAIL_DESTINATARIO`, `SMTP_SERVER`, `SMTP_PORT`. Set these as GitHub Secrets for CI; use `config.json` for local runs (copy from `config.json.example`). Gmail requires an app-specific password.

## Scheduling via GitHub Actions

The workflow `.github/workflows/monitor.yml` runs at 06:00, 12:00, 16:00 UTC (~3×/day). GitHub cron is UTC and best-effort (±15 min delay). After each run it commits the updated `interpelli_visti.json` back to the repo (`[skip ci]` prevents re-triggering). Credentials go in repo Settings → Secrets and variables → Actions.

**Note:** GitHub Pages cannot run this (static hosting only). GitHub Actions is the correct mechanism.

## Building the BAT school list (`build_scuole_bat.py`)

Run once (not part of the regular monitor cycle) to produce `scuole_bat.json`:

```bash
python3 build_scuole_bat.py
```

The script downloads the MIUR open-data CSV `SCUANAGRAFESTAT`, **groups by `CODICEISTITUTORIFERIMENTO`** (the principal institution, not individual plessi), filters to institutions with at least one `SCUOLA PRIMARIA` or `SCUOLA (DELL')INFANZIA` plesso (≈31 IC/circoli; excludes CPIA), normalizes malformed site URLs, adds `www.{codice}.edu.it` fallback, then crawls each institution's site (homepage + albo/pretori subpages) for `customerCode=SC#####`. Schools without an Argo link get `customerCode: null` and are skipped by `argo_albo`. **Review `scuole_bat.json` with the user before using in production** — missing customerCodes are filled in manually by navigating each school's albo.

`scuole_bat.json` schema per entry: `{codMec, nome, comune, siti: [...], pec, gradi: [...], customerCode, piattaforma}`.

If the MIUR CSV URL returns 404 (happens at the start of each new school year), update `MIUR_CSV_URL` in `build_scuole_bat.py`. Find the new URL at `dati.istruzione.it/opendata/opendata/catalogo/elements1/` searching for `SCUANAGRAFESTAT`.

### Argo API details (for `argo_albo` source)

- Listing endpoint: `POST https://www.portaleargo.it/albopretorio/api/public/atti/filters/{customerCode}`
- Required headers: `Content-Type: application/json`, `app_name: isa`, `Origin: https://www.portaleargo.it`, `Referer: https://www.portaleargo.it/albopretorio/online/`
- Body: `{"object": {all nulls}, "page": 0, "size": 100, "sortBy": "dataPubblicazione,numRegistro", "sortDesc": true}`
- Response: `{page, size, totalRows, list: [{id, descrizione, categoria, tipologiaAtto, dataPubblicazione, dataArchiviazione, allegati: [{id, nome, path}]}]}`
- The `customerCode` (format `SC#####`) is Argo-internal and not derivable from the MIUR codice meccanografico.
