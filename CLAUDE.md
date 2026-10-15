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
monitor_interpelli.py   # orchestrator + email + dedup + expiry filter + scadenza resolution
filtering.py            # shared filter logic (codici, dedup ID, date extraction, expiry, link dedupability)
link_resolver.py        # follows posting links (HTML detail pages + attachments) to find deadlines
pdf_utils.py            # deadline extraction from PDF via pypdf (in-memory cache)
dashboard.py            # static dashboard generator (docs/index.html + docs/interpelli.json)
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

1. `esegui()` iterates `get_enabled_sources()` → each `fetch()` returns normalized posting dicts already filtered by target codes. Fetchers only do **cheap text-based** deadline extraction (`estrai_scadenza`); no link-following.
2. `esegui()` discards expired postings using `scadenza_passata()` (logs "⏰ Scartati N scaduti"). Postings with no parseable deadline are kept (better a false positive than a miss).
3. `filtra_nuovi_interpelli()` deduplicates: skips if `stable_id` (sha256 of normalized text) OR `chiave_link(link)` already seen. Links are used for dedup **only if `is_link_dedupabile()`** — generic links (school homepage, whole-albo pages shared by many postings) must not suppress later postings from the same school. Returns `(nuovi, stato)` **without saving**.
4. `risolvi_scadenze()` runs `link_resolver.risolvi_scadenza_da_link()` on NEW postings with empty `scadenza` only (each resolution costs up to ~7 HTTP requests; capped at `MAX_RISOLUZIONI_LINK=40` per run). Postings whose freshly-discovered deadline is already past are dropped (but stay in state).
2b. `riconduci_link_generici()` (before the expiry filter): a posting whose link is a bare Argo-school homepage (istruzionebat/scuolainterpelli often link `https://www.icminervinomurge.edu.it/`) gets the deep-link of the atto from `link_resolver.link_specifico_argo(link, codici, dal, al)`: school found by site domain (`siti` in `scuole_bat.json`), the **only** atto in pubblicazione that is an interpello (not esito) for one of the posting's codes, published in the window (scuolainterpelli's `data_pubblicazione` ±1 day, otherwise the last `GIORNI_RICERCA_ATTO` days). Ambiguous (2+ atti) → link unchanged. Then the deadline is resolvable and the posting dedups with `argo_albo`.
4b. `aggiungi_dettagli()` fills `ip['dettagli']` from `testo_documento` (the PDF/page text in which the deadline was found: set by `argo_albo` and by `risolvi_scadenze` via `link_resolver.risolvi_da_link() -> (scadenza, testo)`) and, for missing keys, from `testo`. No HTTP. `testo_documento` is never persisted.
5. `invia_email()` sends HTML via SMTP+STARTTLS, sorted by deadline urgency, and returns bool. **State is saved only after a successful send** — an SMTP failure leaves state untouched so the next run retries, and the process exits 1 (workflow does not commit state).
6. `riverifica_archivio()` (not on dry-run): up to `MAX_RIVERIFICHE` dashboard records of the last `GIORNI_IGNOTA_ATTIVA` days still without deadline are retried (generic link → Argo atto, `risolvi_da_link`, `argo_archiviato`); updated records are merged by `aggiorna_dashboard` (scadenza, dettagli, archiviato, generic link replaced by a specific one). The archive is deduplicated by `chiave_link` (`_accorpa_doppioni`: first detected wins, gets missing info from duplicates). On the dashboard, a record without deadline whose supplenza started more than `GIORNI_SUPPLENZA_INIZIATA` (2) days ago (`filtering.supplenza_gia_iniziata`, periodo `dal X al Y`, also parsed from `testo` for old records) is "PROBABILMENTE SCADUTO"; the email still notifies it with a "probabilmente già chiuso" note.
7. `aggiorna_dashboard()` appends notified postings to `docs/interpelli.json` and regenerates the static `docs/index.html` (GitHub Pages dashboard). Skipped on `--dry-run`.

### Normalized posting dict fields

Each fetcher returns dicts with: `testo`, `title`, `link`, `tipo`, `scadenza`, `source`, `stable_id`, `data_rilevamento`. `scadenza` is `'DD/MM/YYYY'` or `''` (never `'Non specificata'` — callers display that label for empty string).

### Filtering functions (`filtering.py`)

- `is_sostegno_primaria_infanzia`: matches (a) GPS codes ADEE/ADAA/EEEE/AAAA, (b) old tipo-posto codes `EH`/`CH` as uppercase tokens when SOSTEGNO is also present (UST BAT still publishes "posto sostegno EH" interpelli), (c) keyword fallback `(PRIMARIA|INFANZIA) + (SOSTEGNO|POSTO COMUNE)` for postings with no explicit code (GRADUATORIA excluded). Recall over precision: a missed interpello is worse than a false positive.
- `estrai_scadenza(testo)`: extracts only **application deadlines** (not contract end dates). Recognizes qualified phrases: `ore HH:MM del [giorno] DATE`, `entro le ore X del DATE`, `domanda|candidatura entro DATE`, `manifestazione di interesse entro DATE`, `scadenza|termine domanda DATE`, `entro il termine perentorio del DATE`. Dates can be numeric (`3/9/2026`, `03.09.2026`) or textual (`3 dicembre 2025`, `1° luglio 2026`), optionally preceded by a weekday name. Phrases like `supplenza al DATE`, `dal X al Y`, `fino al DATE` are intentionally ignored. Returns `'DD/MM/YYYY'` (validated) or `''`.
- `is_link_dedupabile(link)`: False for links shared by multiple postings (Argo albo without an atto id, trasparenzascuole page without `#atto-` fragment, bare school homepages).
- `chiave_link(link)`: dedup key stored in the `links` state — `argo:SC#####:ID` for Argo atti (same key for both deep-link formats, `#/dettaglio-atto?customerCode=X&id=Y` and `#/SC#####/atti/Y`, the latter used by istruzionebat.it/scuolainterpelli.it since 2026), the lowercased link otherwise, `''` for generic links. `filtra_nuovi_interpelli` converts the stored legacy links with the same function, so an already-canonical `argo:…` key must be returned unchanged (lowercasing it broke dedup).
- `normalizza_codici(testo)`: rejoins target codes split by spaces (`E EEE`, `EE EE`, `AD EE`) — istruzionebat.it titles contain them. Applied by `is_sostegno_primaria_infanzia` and `identifica_tipo_interpello`.
- `is_esito_interpello(testo)`: verbali, esiti, `individuazione da interpello`, `atto di nomina/individuazione`, annullamenti close an interpello → excluded by `is_sostegno_primaria_infanzia` even with a target code (`individuazione` alone is NOT excluded, it appears in real notices).
- `estrai_dettagli(testo, scadenza)`: details shown in email and dashboard, only those found — `ora_scadenza` (HH:MM, only if attached to the deadline date; tolerates pypdf splitting digits, `ore 1 2:00`), `periodo` (`dal X al Y`, `fino al X`, `fino all'avente diritto`…), `ore` (`24 h/sett`), `sede` (after `sede di servizio:`).
- `parse_data(s)`: parses `'DD/MM/YYYY'` → `date`. Returns `None` on failure.
- `scadenza_passata(s, oggi=None)`: `True` only if parseable AND < today. Non-parseable → `False` (do not discard).
- `compute_stable_id(testo)`: `hashlib.sha256` (not Python's `hash()`, which is salted per-process and would break dedup across GitHub Actions runs).

### Deadline resolution (fallback chain)

1. In-fetcher: `estrai_scadenza(testo)` — title + description + allegato filenames (cheap, no HTTP).
   - **Argo** keeps its in-fetcher fallback: `GET /atti/{attoId}/allegati` (pre-signed S3 ZIP URL) → `pdf_utils.estrai_scadenza_da_zip_url()`. The generic resolver can't handle Argo (JS SPA). No `dataArchiviazione` fallback — that is the albo archiving date, not the application deadline.
2. Post-dedup, NEW postings only: `link_resolver.risolvi_scadenza_da_link(link)`:
   - direct PDF (detected by `%PDF-` magic bytes or Content-Type — **istruzionebat.it attachment pages serve PDFs from extensionless URLs**);
   - HTML detail page text → `estrai_scadenza`;
   - candidate attachment links inside the page (`.pdf`, `wp-content/uploads`, child pages of the post URL, keyword-matched links), downloaded and sniffed as PDF **or DOCX** (magic bytes; DOCX text read from `word/document.xml`); one extra level for WP attachment pages embedding the file. If the main content container yields nothing, the **whole page** is retried — some themes (e.g. "Design Scuole Italia" on .edu.it sites) place the attachments section outside `<main>`/`entry-content`.
   - `portaleargo.it` deep-links (either format, parsed by `filtering.parse_link_argo`) resolved via the Argo REST API (allegati → pre-signed ZIP → PDFs), not by fetching the SPA page.
   - `trasparenzascuole.it` direct-document links (`view_doc.aspx?p=...`) downloaded via `curl_cffi` chrome131 impersonation (works from residential IPs; from GitHub Actions the Cloudflare WAF returns 403 → resolver returns `''` silently). Albo pages (`APDPublic`) still bail out (server-side session required).
3. Stale detection for postings with no deadline: `link_resolver.argo_archiviato(link)` — an Argo atto with past archiving date (`argo_albo.data_archiviazione()`: `dataArchiviazioneEffettiva`, format `DD/MM/YYYY`) OR missing from a *complete* albo listing (`totalRows <= len(list)`; absence from a truncated listing proves nothing) is dead and gets dropped before notification. `argo_albo` also skips archived atti at fetch time. (The archiving date is never used as the *application deadline*. Note: after archiving, Argo empties the allegati ZIP, so the deadline must be read at first detection.)
4. If no qualified deadline found → `scadenza = ''`. The interpello is still notified with a "verify immediately" warning (false negative is worse than false positive). On the dashboard, unknown-deadline postings older than 15 days (`GIORNI_IGNOTA_ATTIVA`) are shown as "PROBABILMENTE SCADUTO" and excluded from the "Attivi" filter.

One-off backfill of the dashboard archive from historical reports: `python3 tools/backfill_dashboard.py`.

### Sources

- **`istruzionebat_rss`**: `feedparser` on `istruzionebat.it/category/interpello/feed/`. Each RSS entry is one interpello. **The feed stopped updating in February 2026** (the index page kept going): the source reports "Feed fermo" when the newest entry is older than `GIORNI_FEED_FERMO`.
- **`istruzionebat_html`** (main UST source in 2026-27): BeautifulSoup on the yearly index page `istruzionebat.it/interpelli/a-s-YYYY-YYYY/`, URL computed by `url_anno_scolastico()` (new year from September; falls back to the previous year's page if the new one doesn't exist yet). Entries are `<h2>/<h3>` inside `div.testolungo` (older years: `li/p/h4` in `entry-content`); reports an error if no entry is found (page structure changed).
- **`scuolainterpelli_rss`** (secondary): `feedparser` on `scuolainterpelli.it/feed/`. The RSS `content:encoded` is a big HTML blob organized by region (`<h2>`) → province subheading (`Interpelli pubblicati da: <strong>NAME</strong>`) → entries `<p>CODES – <a href=…>VISUALIZZA INTERPELLI</a></p>` followed by `<p><em>12 ottobre 2026</em></p>`. Client-filters for PUGLIA and BAT province keywords (`BAT_PROVINCE_KEYWORDS`, whole-word match: `ALESSANDRIA` contains `ANDRIA`). The entry text is always the same, so `stable_id = sha256(codes + link + date)`; entries published more than `MAX_GIORNI` (3) days ago are skipped (the feed keeps ~2 weeks of issues). Links are often the school homepage or the UST site rather than the specific interpello.

- **`argo_albo`** (per-school): `lista_atti()` POSTs to `portaleargo.it/albopretorio/api/public/atti/filters/{customerCode}` for each `piattaforma=="argo"` school in `scuole_bat.json`. The category is free text, different per school (or null), so atti are selected by `descrizione` (contains "interpell" or a target code); annulled, archived, graduatorie and esiti/verbali are skipped. The listing no longer includes allegato names: when the description has no class code at all (`_CLASSE_RE`), the allegati ZIP is downloaded and the codes are looked up in the PDFs (`pdf_utils.testo_da_zip_url`). Link `#/{customerCode}/atti/{id}`, `stable_id = sha256("argo-{customerCode}-{attoId}")`. CustomerCode is in `scuola['params']['customerCode']`.

- **`nuvola_albo`** (per-school): GET `nuvola.madisoft.it/bacheca-digitale/bacheca/{codMiur}/{tipologia}/IN_PUBBLICAZIONE/0/show` for each `piattaforma=="nuvola"` school. First discovers available tipologie from the school's root page (if none, tries 5,1,2,3,4). Parses an HTML `<table>` with BeautifulSoup — no header row, all `<tr>` are data rows. `stable_id` uses the doc ID from the link path (`/bacheca-digitale/{id}/documento/{codMiur}`). codMiur lives in `scuola['params']['codMiur']`.

- **`trasparenzascuole_albo`** (per-school): Two-step for each `piattaforma=="trasparenzascuole"` school: (1) GET `trasparenzascuole.it/Public/APDPublic_ExtV2.aspx?CF={cf}` to extract the GUID from `button[data-action=GET_APD_TABLE][data-cust-id]`; (2) POST JSON to `trasparenzascuole.it/Ajax/APP_Ajax_Get.aspx?action=GET_APD_TABLE&Others={custId}` with body `{statopubblicazione:"0", ..., PageNumber:"N"}` for each page. Response is HTML (not JSON). No `<thead>` — all `<tr>` are data rows. Paginates using `PageNumber` in the JSON body. CF lives in `scuola['params']['codiceFiscale']`.

Adding a new source: create a subclass of `BaseSource` in `sources/`, implement `fetch()`, register it in `sources/__init__.py:get_enabled_sources()`. Report problems with `self.segnala_errore(msg)` (never a bare `print` + `return []`): `esegui()` collects `source.errori` into the run report ("Sorgenti con problemi"), emits `::warning` annotations on GitHub Actions and lists them in the email footer — without failing the job (trasparenzascuole is WAF-blocked on every CI run).

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

**Send window:** the monitor does nothing outside 08:00–22:00 Europe/Rome (`in_fascia_invio()`, `ORA_INIZIO_INVIO`/`ORA_FINE_INVIO`; DST-aware): no fetch, no email, state untouched, so night postings arrive with the first morning run. `--dry-run` ignores the window.

**Triggers:** the main trigger is external (cron-job.org calling the `workflow_dispatch` API every 30 minutes, with a fine-grained PAT with Actions read/write on this repo), because GitHub drops many scheduled runs (October 2026: 2-3 runs/day out of 13). The workflow's own cron (`17 6-20 * * *` UTC, minute 17 because top-of-the-hour runs are dropped more often) is the backup; it covers 08–22 Italy in both DST and standard time, the code enforces the exact window. BAT interpelli are often published around 17-18 and expire the next morning. A `concurrency` group prevents overlapping runs. After each run it commits `interpelli_visti.json`, `reports/` and `docs/` back to the repo (`[skip ci]` prevents re-triggering). The monitor step has `continue-on-error: true`; the commit step always commits `reports/` and `docs/` (so un-notified postings stay visible on the dashboard) but adds `interpelli_visti.json` only when `steps.monitor.outcome == 'success'` — on SMTP failure the monitor exits 1 and state must not be committed, so the next run retries the notification. A final step re-fails the job so GitHub still sends the "Run failed" email (the only alarm when SMTP is broken). SMTP errors log the failing phase (connessione/starttls/login/invio); a `535` (`SMTPAuthenticationError`) means the Gmail app password was revoked — regenerate it and update the `PASSWORD_EMAIL` secret (set it from a real terminal or the web UI: `! gh secret set` has no TTY and stores an empty value). Credentials go in repo Settings → Secrets and variables → Actions.

**Note:** GitHub Pages cannot run this (static hosting only) but serves the generated dashboard from `docs/` (Settings → Pages → Deploy from branch → main, `/docs`). GitHub Actions is the correct mechanism for the monitor itself.

## Building the BAT school list (`build_scuole_bat.py`)

Run once (not part of the regular monitor cycle) to produce `scuole_bat.json`. Verify trasparenzascuole CFs on the IPA index (`indicepa.gov.it/ipa-dati/api/3/action/datastore_search`, field `Codice_MIUR`): in October 2026 two CFs belonged to same-name schools in other provinces.

```bash
python3 build_scuole_bat.py
```

The script downloads the MIUR open-data CSV `SCUANAGRAFESTAT`, **groups by `CODICEISTITUTORIFERIMENTO`** (principal institution, not individual plessi), filters to institutions with at least one `SCUOLA PRIMARIA` or `SCUOLA (DELL')INFANZIA` plesso (≈31 IC/circoli; excludes CPIA), then crawls each school's site for `customerCode=SC#####`. After crawling, applies `MAPPING_MANUALE` (constant in the script) — manual mapping wins over auto-crawling. Schools not in the manual mapping that weren't auto-detected get `piattaforma=null`.

**Platform breakdown (31 schools, October 2026):** 18 Argo, 8 Trasparenzascuole, 2 Nuvola, 3 null.

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

`siti` is used to map a homepage link to the school (`link_specifico_argo`); schools missing from the MIUR CSV get it from `SITI_MANUALI` (taken from the IPA index, where some schools are registered with the old `BA…` code).

`params` by platform: `argo` → `{customerCode}`, `nuvola` → `{codMiur}`, `trasparenzascuole` → `{codiceFiscale}`, `null` → absent.

**Updating `MAPPING_MANUALE`:** edit `MAPPING_MANUALE` in `build_scuole_bat.py`, then re-run the script to regenerate `scuole_bat.json`. If a school changes platform, update the entry in the map.

If the MIUR CSV URL returns 404 (start of new school year), update `MIUR_CSV_URL` in `build_scuole_bat.py`. Find the new URL at `dati.istruzione.it/opendata/opendata/catalogo/elements1/` searching for `SCUANAGRAFESTAT`.

### Argo API details (for `argo_albo` source)

- Listing endpoint: `POST https://www.portaleargo.it/albopretorio/api/public/atti/filters/{customerCode}`
- Required headers: `Content-Type: application/json`, `app_name: isa`, `Origin: https://www.portaleargo.it`, `Referer: https://www.portaleargo.it/albopretorio/online/`
- Body: `{"object": {all nulls}, "page": 0, "size": 100, "sortBy": "dataPubblicazione", "sortDesc": true}` — **`sortBy` must be the single field**: with `"dataPubblicazione,numRegistro"` the order is ascending whatever `sortDesc` says, so schools with >100 atti lost the most recent ones.
- Response (schema changed in 2026): `{page, size, totalRows, list: [{id, codCli, descrizione, categoriaDenominazione (free text, may be null), categoria (null), tipologiaAttoDenominazione, dataPubblicazione, dataArchiviazioneEffettiva, annullato, numAllegati, allegati: [] (always empty in the listing)}]}`. A response without `list` raises `ValueError` (reported as a source error).
- `customerCode` format: `SC#####` for IC, `SE#####` for circoli didattici. Argo-internal, not derivable from codice meccanografico.
- **Allegati download**: `GET /atti/{attoId}/allegati` (same headers) → returns a temporary pre-signed S3 URL (plain text/JSON string) pointing to a ZIP containing all attachments. The ZIP URL is valid for a few minutes. Use `pdf_utils.estrai_scadenza_da_zip_url()` to extract the application deadline from PDFs inside. The `path` field in the allegato JSON is NOT directly downloadable — it's an S3 key protected by access control.

### Nuvola Madisoft API details (for `nuvola_albo` source)

- URL: `GET https://nuvola.madisoft.it/bacheca-digitale/bacheca/{codMiur}/{tipologia}/IN_PUBBLICAZIONE/0/show`
- `codMiur` is the MIUR codice meccanografico (often starts with `BA`, not `BT`, for the reference institution)
- The adapter discovers available tipologie from the school root page first; if none found, tries `[5, 1, 2, 3, 4]`
- Response: server-side HTML `<table>`; columns differ per school/tipologia, so `Oggetto` and `Data pubblicazione su bacheca` are located from the `<th>` header row. Data rows are those with a `/bacheca-digitale/{id}/documento/` link (skips the filter row). The board keeps interpelli "in pubblicazione" for months/years: rows published more than `MAX_GIORNI_PUBBLICAZIONE` (30) days ago are skipped.

### Trasparenzascuole.it API details (for `trasparenzascuole_albo` source)

- Step 1 GET: `https://www.trasparenzascuole.it/Public/APDPublic_ExtV2.aspx?CF={codiceFiscale}` → extract `button[data-action=GET_APD_TABLE][data-cust-id]` (GUID per school)
- **Step 2 GET (required)**: `https://www.trasparenzascuole.it/Ajax/APP_Ajax_Get.aspx?action=INIT_APD&Others={custId}&_={timestamp_ms}` — must be called before the POST, otherwise POST always returns "Nessuno atto trovato" (server-side session not initialized)
- Step 3 POST JSON: `https://www.trasparenzascuole.it/Ajax/APP_Ajax_Get.aspx?action=GET_APD_TABLE&Others={custId}` with body `{statopubblicazione:"0", idtipoatto:"", annoselezionato:"", numeroprogressivo:"", numeroprotocollo:"", oggetto:"", dataInizio:"", dataFine:"", searchfield:""}` — add `PageNumber:"N"` for pages > 1
- `statopubblicazione:"0"` = atti in corso di pubblicazione only (never scaduti); omit or use `""` for all-time history
- Response: HTML fragment. Row structure: `<tr><td>num</td><td><i>Oggetto: ...</i></td><td>pubDate/scadDate/badge</td><td>Tipo</td><td><button data-idatto="GUID"></td></tr>`
- Stable_id: `sha256("trasparenzascuole-{cf}-{data-idatto}")` — the GUID per act is stable
- Pagination: parse "Totale pagine X di N"; increment `PageNumber` in body; 5 results per page typical
- `GET_APD_ATTO` (allegati): not called — requires active server session, returns error outside the browser flow. The page URL is used as `link` instead.
- **Note CI**: the source uses `curl_cffi` with `impersonate="chrome131"` instead of `requests`. This impersonates Chrome's TLS handshake (JA3 + HTTP/2 fingerprint), bypassing the Cloudflare WAF that blocks `requests`/OpenSSL TLS signatures from GitHub Actions Azure IPs. Other sources keep using `requests`.

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
