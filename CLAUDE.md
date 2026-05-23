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
  argo_albo.py          # per-school: Argo albo pretorio REST API
  nuvola_albo.py        # per-school: Nuvola Madisoft bacheca digitale (server-side HTML)
  trasparenzascuole_albo.py  # per-school: Trasparenzascuole.it (Axios) AJAX API
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

- **`argo_albo`** (per-school): POST to `portaleargo.it/albopretorio/api/public/atti/filters/{customerCode}` for each `piattaforma=="argo"` school in `scuole_bat.json`. Filters category "C2 - Interpelli", excludes graduatorie. Matches ADEE/ADAA/EEEE/AAAA in `descrizione` AND allegato filenames. `stable_id = sha256("argo-{customerCode}-{attoId}")`. CustomerCode is in `scuola['params']['customerCode']`.

- **`nuvola_albo`** (per-school): GET `nuvola.madisoft.it/bacheca-digitale/bacheca/{codMiur}/{tipologia}/IN_PUBBLICAZIONE/0/show` for each `piattaforma=="nuvola"` school. First discovers available tipologie from the school's root page (if none, tries 5,1,2,3,4). Parses an HTML `<table>` with BeautifulSoup — no header row, all `<tr>` are data rows. `stable_id` uses the doc ID from the link path (`/bacheca-digitale/{id}/documento/{codMiur}`). codMiur lives in `scuola['params']['codMiur']`.

- **`trasparenzascuole_albo`** (per-school): Two-step for each `piattaforma=="trasparenzascuole"` school: (1) GET `trasparenzascuole.it/Public/APDPublic_ExtV2.aspx?CF={cf}` to extract the GUID from `button[data-action=GET_APD_TABLE][data-cust-id]`; (2) POST JSON to `trasparenzascuole.it/Ajax/APP_Ajax_Get.aspx?action=GET_APD_TABLE&Others={custId}` with body `{statopubblicazione:"0", ..., PageNumber:"N"}` for each page. Response is HTML (not JSON). No `<thead>` — all `<tr>` are data rows. Paginates using `PageNumber` in the JSON body. CF lives in `scuola['params']['codiceFiscale']`.

Adding a new source: create a subclass of `BaseSource` in `sources/`, implement `fetch()`, register it in `sources/__init__.py:get_enabled_sources()`.

### Persistent files

| File | Purpose |
|---|---|
| `config.json` | SMTP credentials (never commit — in `.gitignore`) |
| `interpelli_visti.json` | `{"ids": [...sha256...], "links": [...urls...]}` for seen postings |
| `scuole_bat.json` | BAT school list with platform mapping; generated by `build_scuole_bat.py` |
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

The script downloads the MIUR open-data CSV `SCUANAGRAFESTAT`, **groups by `CODICEISTITUTORIFERIMENTO`** (principal institution, not individual plessi), filters to institutions with at least one `SCUOLA PRIMARIA` or `SCUOLA (DELL')INFANZIA` plesso (≈31 IC/circoli; excludes CPIA), then crawls each school's site for `customerCode=SC#####`. After crawling, applies `MAPPING_MANUALE` (constant in the script) — manual mapping wins over auto-crawling. Schools not in the manual mapping that weren't auto-detected get `piattaforma=null`.

**Platform breakdown (31 schools, 2025-26):** 17 Argo, 7 Trasparenzascuole, 1 Nuvola, 6 null (1 Spaggiari JS-side, 2 custom, 3 unknown).

`scuole_bat.json` schema per entry:
```json
{
  "codMec": "BTIC86200Q",
  "nome": "...",
  "comune": "ANDRIA",
  "siti": ["http://..."],
  "pec": "...@pec.istruzione.it",
  "gradi": ["SCUOLA PRIMARIA", ...],
  "piattaforma": "argo",
  "params": {"customerCode": "SC27220"}
}
```

`params` by platform: `argo` → `{customerCode}`, `nuvola` → `{codMiur}`, `trasparenzascuole` → `{codiceFiscale}`, `null` → absent.

**Updating `MAPPING_MANUALE`:** edit `MAPPING_MANUALE` in `build_scuole_bat.py`, then re-run the script to regenerate `scuole_bat.json`. If a school changes platform, update the entry in the map.

If the MIUR CSV URL returns 404 (start of new school year), update `MIUR_CSV_URL` in `build_scuole_bat.py`. Find the new URL at `dati.istruzione.it/opendata/opendata/catalogo/elements1/` searching for `SCUANAGRAFESTAT`.

### Argo API details (for `argo_albo` source)

- Listing endpoint: `POST https://www.portaleargo.it/albopretorio/api/public/atti/filters/{customerCode}`
- Required headers: `Content-Type: application/json`, `app_name: isa`, `Origin: https://www.portaleargo.it`, `Referer: https://www.portaleargo.it/albopretorio/online/`
- Body: `{"object": {all nulls}, "page": 0, "size": 100, "sortBy": "dataPubblicazione,numRegistro", "sortDesc": true}`
- Response: `{page, size, totalRows, list: [{id, descrizione, categoria, tipologiaAtto, dataPubblicazione, dataArchiviazione, allegati: [{id, nome, path}]}]}`
- `customerCode` format: `SC#####` for IC, `SE#####` for circoli didattici. Argo-internal, not derivable from codice meccanografico.

### Nuvola Madisoft API details (for `nuvola_albo` source)

- URL: `GET https://nuvola.madisoft.it/bacheca-digitale/bacheca/{codMiur}/{tipologia}/IN_PUBBLICAZIONE/0/show`
- `codMiur` is the MIUR codice meccanografico (often starts with `BA`, not `BT`, for the reference institution)
- The adapter discovers available tipologie from the school root page first; if none found, tries `[5, 1, 2, 3, 4]`
- Response: server-side HTML with `<table>` (no header row — all `<tr>` are data)

### Trasparenzascuole.it API details (for `trasparenzascuole_albo` source)

- Step 1 GET: `https://www.trasparenzascuole.it/Public/APDPublic_ExtV2.aspx?CF={codiceFiscale}` → extract `button[data-action=GET_APD_TABLE][data-cust-id]` (GUID per school)
- **Step 2 GET (required)**: `https://www.trasparenzascuole.it/Ajax/APP_Ajax_Get.aspx?action=INIT_APD&Others={custId}&_={timestamp_ms}` — must be called before the POST, otherwise POST always returns "Nessuno atto trovato" (server-side session not initialized)
- Step 3 POST JSON: `https://www.trasparenzascuole.it/Ajax/APP_Ajax_Get.aspx?action=GET_APD_TABLE&Others={custId}` with body `{statopubblicazione:"0", idtipoatto:"", annoselezionato:"", numeroprogressivo:"", numeroprotocollo:"", oggetto:"", dataInizio:"", dataFine:"", searchfield:""}` — add `PageNumber:"N"` for pages > 1
- `statopubblicazione:"0"` = atti in corso di pubblicazione only (never scaduti); omit or use `""` for all-time history
- Response: HTML fragment. Row structure: `<tr><td>num</td><td><i>Oggetto: ...</i></td><td>pubDate/scadDate/badge</td><td>Tipo</td><td><button data-idatto="GUID"></td></tr>`
- Stable_id: `sha256("trasparenzascuole-{cf}-{data-idatto}")` — the GUID per act is stable
- Pagination: parse "Totale pagine X di N"; increment `PageNumber` in body; 5 results per page typical
- `GET_APD_ATTO` (allegati): not called — requires active server session, returns error outside the browser flow. The page URL is used as `link` instead.

## Discovering new AJAX sources (`tools/discover_ajax.py`)

When a new school platform behaves unexpectedly or you can't figure out its API from static analysis, use the Playwright-based discovery tool to capture real browser traffic:

```bash
# One-time setup (dev only — not in requirements.txt)
pip install -r requirements-dev.txt
playwright install chromium

# Run discovery: navigates URL, clicks selector, captures all XHR/fetch requests
python3 tools/discover_ajax.py \
  --url "https://www.example-school.it/albo?CF=12345" \
  --click '[data-action="LOAD"]' \
  --output tools/captures/example_12345.json
  # add --headed to see the browser window
  # add --no-click to just capture page load without clicking
```

The JSON output (`tools/captures/*.json`, gitignored) contains each intercepted XHR: method, URL, request headers + body, response status + body (first 64 KB). Read it to identify:
1. The exact `Content-Type` and body format of the POST (JSON vs form-encoded)
2. Any required pre-flight requests (like `INIT_APD` for Trasparenzascuole)
3. Pagination parameters
4. How to extract stable IDs (GUIDs, numeric IDs in response HTML)

Then implement the source as `sources/<platform>_albo.py` using plain `requests`, register in `sources/__init__.py`, and test with `--dry-run --source <name>`. Playwright is **not** used at runtime.
