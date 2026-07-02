"""
Dashboard statica degli interpelli notificati.

Ad ogni run i nuovi interpelli vengono accodati a docs/interpelli.json e la pagina
docs/index.html viene rigenerata con i dati incorporati (funziona anche aprendo il
file in locale, senza server). Pubblicandola con GitHub Pages (Settings → Pages →
branch main, cartella /docs) diventa consultabile da qualsiasi dispositivo.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List

from filtering import parse_data

GIORNI_RETENTION = 120


def aggiorna_dashboard(nuovi: List[Dict], dry_run: bool = False, docs_dir: Path = Path('docs')):
    if dry_run:
        return
    docs_dir = Path(docs_dir)
    docs_dir.mkdir(parents=True, exist_ok=True)
    json_path = docs_dir / 'interpelli.json'

    archivio: List[Dict] = []
    if json_path.exists():
        try:
            archivio = json.loads(json_path.read_text(encoding='utf-8'))
        except Exception:
            archivio = []

    per_id = {r.get('stable_id'): r for r in archivio}
    for ip in nuovi:
        esistente = per_id.get(ip['stable_id'])
        if esistente is not None:
            # Integra le informazioni scoperte dopo la prima pubblicazione
            # (backfill, ri-risoluzione scadenze, rilevazione atti archiviati)
            if ip.get('scadenza') and not esistente.get('scadenza'):
                esistente['scadenza'] = ip['scadenza']
            if ip.get('archiviato'):
                esistente['archiviato'] = True
            continue
        archivio.append({
            'title': ip.get('title', ''),
            'tipo': ip.get('tipo', ''),
            'scadenza': ip.get('scadenza', ''),
            'link': ip.get('link', ''),
            'source': ip.get('source', ''),
            'stable_id': ip.get('stable_id', ''),
            'data_rilevamento': ip.get('data_rilevamento', ''),
            'testo': (ip.get('testo') or '')[:400],
            'archiviato': bool(ip.get('archiviato')),
        })

    cutoff = datetime.now() - timedelta(days=GIORNI_RETENTION)
    def recente(r):
        try:
            return datetime.fromisoformat(r.get('data_rilevamento', '')) >= cutoff
        except ValueError:
            return True
    archivio = [r for r in archivio if recente(r)]

    # Più recenti prima
    archivio.sort(key=lambda r: r.get('data_rilevamento', ''), reverse=True)

    json_path.write_text(json.dumps(archivio, indent=1, ensure_ascii=False), encoding='utf-8')
    (docs_dir / 'index.html').write_text(_genera_html(archivio), encoding='utf-8')
    print(f"🖥  Dashboard aggiornata: {docs_dir / 'index.html'} ({len(archivio)} interpelli)")


# Un interpello senza scadenza rilevabile più vecchio di così è quasi certamente
# chiuso (le finestre di candidatura durano pochi giorni)
GIORNI_IGNOTA_ATTIVA = 15


def _genera_html(archivio: List[Dict]) -> str:
    oggi = datetime.now().date()
    for r in archivio:
        d = parse_data(r.get('scadenza', ''))
        if r.get('archiviato'):
            # atto non più in pubblicazione sull'albo (es. Argo archiviato)
            r['_stato'] = 'stantio'
            r['_giorni'] = None
        elif d is None:
            r['_stato'] = 'ignota'
            r['_giorni'] = None
            try:
                ril = datetime.fromisoformat(r.get('data_rilevamento', '')).date()
                if (oggi - ril).days > GIORNI_IGNOTA_ATTIVA:
                    r['_stato'] = 'stantio'
            except ValueError:
                pass
        elif d < oggi:
            r['_stato'] = 'scaduto'
            r['_giorni'] = (d - oggi).days
        else:
            r['_stato'] = 'attivo'
            r['_giorni'] = (d - oggi).days

    dati = json.dumps(archivio, ensure_ascii=False).replace('</', '<\\/')
    aggiornato = datetime.now().strftime('%d/%m/%Y %H:%M')

    return """<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Interpelli BAT — Primaria e Infanzia</title>
<style>
  :root { --blu:#2c5f8a; --rosso:#c0392b; --verde:#27ae60; --grigio:#7f8c8d; }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, "Segoe UI", Roboto, Arial, sans-serif; margin:0;
         background:#f4f6f8; color:#2c3e50; }
  header { background:var(--blu); color:#fff; padding:18px 16px; }
  header h1 { margin:0; font-size:1.25rem; }
  header p { margin:4px 0 0; font-size:.8rem; opacity:.85; }
  .wrap { max-width:860px; margin:0 auto; padding:12px 16px 40px; }
  .controls { display:flex; gap:8px; flex-wrap:wrap; margin:14px 0; }
  .controls input { flex:1 1 200px; padding:8px 10px; border:1px solid #ccc; border-radius:6px; font-size:.95rem; }
  .controls button { padding:8px 12px; border:1px solid #ccc; border-radius:6px; background:#fff;
                     cursor:pointer; font-size:.85rem; }
  .controls button.on { background:var(--blu); color:#fff; border-color:var(--blu); }
  .card { background:#fff; border-radius:8px; padding:14px 16px; margin-bottom:10px;
          border-left:4px solid var(--grigio); box-shadow:0 1px 2px rgba(0,0,0,.06); }
  .card.attivo { border-left-color:var(--verde); }
  .card.urgente { border-left-color:var(--rosso); }
  .card.scaduto { opacity:.55; }
  .card h3 { margin:0 0 6px; font-size:.98rem; line-height:1.35; }
  .badge { display:inline-block; font-size:.72rem; font-weight:700; padding:2px 8px;
           border-radius:10px; margin-right:6px; }
  .b-attivo { background:#e8f8ef; color:var(--verde); }
  .b-urgente { background:#fdecea; color:var(--rosso); }
  .b-scaduto { background:#eee; color:var(--grigio); }
  .b-ignota { background:#fef5e7; color:#b9770e; }
  .meta { font-size:.8rem; color:var(--grigio); margin:4px 0; }
  .card a { color:var(--blu); font-size:.88rem; }
  .vuoto { text-align:center; color:var(--grigio); padding:40px 0; }
  .btn-lancia { margin-top:10px; padding:8px 14px; border:1px solid rgba(255,255,255,.5);
                border-radius:6px; background:rgba(255,255,255,.12); color:#fff;
                cursor:pointer; font-size:.85rem; font-weight:600; }
  .btn-lancia:hover { background:rgba(255,255,255,.22); }
  .overlay { position:fixed; inset:0; background:rgba(0,0,0,.45); display:none;
             align-items:flex-start; justify-content:center; padding:24px 16px; z-index:100;
             overflow-y:auto; }
  .overlay.aperto { display:flex; }
  .pannello { background:#fff; border-radius:10px; max-width:520px; width:100%;
              padding:18px 20px; box-shadow:0 8px 30px rgba(0,0,0,.25); }
  .pannello h2 { margin:0 0 10px; font-size:1.05rem; color:var(--blu); }
  .pannello p, .pannello li { font-size:.88rem; line-height:1.5; }
  .pannello ol { padding-left:20px; margin:8px 0; }
  .pannello .chiudi { float:right; border:none; background:none; font-size:1.3rem;
                      cursor:pointer; color:var(--grigio); line-height:1; padding:2px 6px; }
  .pannello .azione { display:inline-block; margin:6px 6px 6px 0; padding:9px 14px;
                      border-radius:6px; font-size:.88rem; font-weight:600; cursor:pointer;
                      text-decoration:none; border:1px solid var(--blu); }
  .pannello .azione.pieno { background:var(--blu); color:#fff; }
  .pannello .azione.vuota { background:#fff; color:var(--blu); }
  .pannello input[type=password], .pannello input[type=text] {
      width:100%; padding:8px 10px; border:1px solid #ccc; border-radius:6px;
      font-size:.9rem; margin:6px 0; }
  .msg { padding:10px 12px; border-radius:6px; font-size:.9rem; margin:10px 0; }
  .msg.ok { background:#e8f8ef; color:#1e8449; }
  .msg.err { background:#fdecea; color:var(--rosso); }
  .msg.attesa { background:#eef3f8; color:var(--blu); }
  .nota-token { font-size:.78rem; color:var(--grigio); }
  .link-mini { font-size:.8rem; color:var(--blu); cursor:pointer; text-decoration:underline;
               background:none; border:none; padding:0; }
  details.istruzioni { background:#f4f6f8; border-radius:6px; padding:8px 12px; margin:8px 0; }
  details.istruzioni summary { cursor:pointer; font-size:.88rem; font-weight:600; color:var(--blu); }
</style>
</head>
<body>
<header>
  <h1>📋 Interpelli BAT — Primaria e Infanzia</h1>
  <p>ADEE · ADAA · EEEE · AAAA — aggiornato al __AGGIORNATO__</p>
  <button id="btn-lancia" class="btn-lancia">🔄 Lancia ricerca</button>
</header>
<div id="overlay" class="overlay">
  <div class="pannello">
    <button class="chiudi" id="chiudi-pannello" title="Chiudi">✕</button>
    <h2>🔄 Lancia una ricerca adesso</h2>
    <div id="pannello-corpo"></div>
  </div>
</div>
<div class="wrap">
  <div class="controls">
    <input id="q" type="search" placeholder="Cerca scuola, comune, tipo...">
    <button data-f="attivi" class="on">Attivi</button>
    <button data-f="tutti">Tutti</button>
    <button data-f="sostegno">Sostegno</button>
    <button data-f="comune">Posto comune</button>
  </div>
  <div id="lista"></div>
</div>
<script>
const DATA = __DATA__;
let filtro = 'attivi';
const q = document.getElementById('q');
const lista = document.getElementById('lista');

function badge(r) {
  if (r._stato === 'scaduto') return '<span class="badge b-scaduto">SCADUTO</span>';
  if (r._stato === 'stantio') return '<span class="badge b-scaduto">PROBABILMENTE SCADUTO</span>';
  if (r._stato === 'ignota')  return '<span class="badge b-ignota">SCADENZA DA VERIFICARE</span>';
  if (r._giorni <= 1) return '<span class="badge b-urgente">SCADE ' + (r._giorni === 0 ? 'OGGI' : 'DOMANI') + '</span>';
  return '<span class="badge b-attivo">ATTIVO — ' + r._giorni + ' giorni</span>';
}
function card(r) {
  const cls = (r._stato === 'scaduto' || r._stato === 'stantio') ? 'scaduto'
    : (r._stato === 'attivo' && r._giorni <= 1 ? 'urgente' : r._stato);
  return '<div class="card ' + cls + '">'
    + '<h3>' + esc(r.title) + '</h3>'
    + '<div>' + badge(r) + '<span class="badge" style="background:#eef3f8;color:var(--blu)">' + esc(r.tipo) + '</span></div>'
    + '<div class="meta">📅 Scadenza: ' + (r.scadenza || 'non rilevata')
    + ' · rilevato il ' + (r.data_rilevamento || '').slice(0,10).split('-').reverse().join('/')
    + ' · fonte: ' + esc(r.source) + '</div>'
    + (r.link ? '<a href="' + escAttr(r.link) + '" target="_blank" rel="noopener">Apri l\\'interpello →</a>' : '')
    + '</div>';
}
function esc(s) { return (s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function escAttr(s) { return esc(s).replace(/"/g,'&quot;'); }
function render() {
  const t = q.value.trim().toLowerCase();
  let rows = DATA.filter(r => {
    if (filtro === 'attivi' && (r._stato === 'scaduto' || r._stato === 'stantio')) return false;
    if (filtro === 'sostegno' && !/SOSTEGNO/i.test(r.tipo)) return false;
    if (filtro === 'comune' && !/COMUNE/i.test(r.tipo)) return false;
    if (t && !(r.title + ' ' + r.tipo + ' ' + r.testo).toLowerCase().includes(t)) return false;
    return true;
  });
  // urgenti prima (scadenza nota ascendente), poi senza scadenza, poi scaduti
  rows.sort((a, b) => {
    const rank = s => (s._stato === 'scaduto' || s._stato === 'stantio') ? 2 : (s._stato === 'ignota' ? 1 : 0);
    if (rank(a) !== rank(b)) return rank(a) - rank(b);
    if (a._stato === 'attivo' && b._stato === 'attivo') return a._giorni - b._giorni;
    return (b.data_rilevamento || '').localeCompare(a.data_rilevamento || '');
  });
  lista.innerHTML = rows.length ? rows.map(card).join('') : '<div class="vuoto">Nessun interpello trovato.</div>';
}
document.querySelectorAll('.controls button').forEach(b => b.addEventListener('click', () => {
  document.querySelectorAll('.controls button').forEach(x => x.classList.remove('on'));
  b.classList.add('on');
  filtro = b.dataset.f;
  render();
}));
q.addEventListener('input', render);
render();

// ---- Lancia ricerca: avvia il workflow GitHub Actions (workflow_dispatch) ----
const GH_API = 'https://api.github.com/repos/AndreaValenziano/app_interpelli/actions/workflows/monitor.yml/dispatches';
const GH_ACTIONS_URL = 'https://github.com/AndreaValenziano/app_interpelli/actions/workflows/monitor.yml';
const TOKEN_KEY = 'gh_token';
const overlay = document.getElementById('overlay');
const corpo = document.getElementById('pannello-corpo');

function apriPannello() { overlay.classList.add('aperto'); }
function chiudiPannello() { overlay.classList.remove('aperto'); }
document.getElementById('chiudi-pannello').addEventListener('click', chiudiPannello);
overlay.addEventListener('click', e => { if (e.target === overlay) chiudiPannello(); });

function vistaSetup(errore) {
  corpo.innerHTML =
    (errore ? '<div class="msg err">⚠️ ' + errore + '</div>' : '')
    + '<p>Questa pagina è un sito statico: la ricerca vera gira su GitHub. Puoi avviarla in due modi.</p>'
    + '<p><strong>Opzione 1 — dal sito GitHub (più semplice):</strong><br>'
    + '<a class="azione pieno" href="' + GH_ACTIONS_URL + '" target="_blank" rel="noopener">Avvia da GitHub →</a><br>'
    + '<span class="nota-token">Nella pagina che si apre clicca il pulsante grigio “Run workflow” a destra, poi quello verde di conferma. Serve essere collegati a GitHub.</span></p>'
    + '<p><strong>Opzione 2 — direttamente da questo pulsante (configurazione una tantum):</strong></p>'
    + '<details class="istruzioni"><summary>Come creare il codice di accesso (token)</summary>'
    + '<ol>'
    + '<li>Apri <a href="https://github.com/settings/personal-access-tokens/new" target="_blank" rel="noopener">github.com/settings/personal-access-tokens/new</a> (devi essere collegato a GitHub).</li>'
    + '<li>In “Token name” scrivi un nome qualsiasi, es. <em>dashboard interpelli</em>.</li>'
    + '<li>In “Repository access” scegli <em>Only select repositories</em> e seleziona <strong>app_interpelli</strong>.</li>'
    + '<li>Apri “Repository permissions” e imposta <strong>Actions</strong> su <em>Read and write</em>.</li>'
    + '<li>Clicca “Generate token” in fondo e copia il codice che inizia con <code>github_pat_</code>.</li>'
    + '</ol></details>'
    + '<input id="token-input" type="password" placeholder="Incolla qui il token (github_pat_...)" autocomplete="off">'
    + '<p class="nota-token">🔒 Il token resta salvato solo in questo browser e viene usato solo per parlare con GitHub. Non viene inviato altrove.</p>'
    + '<button class="azione vuota" id="salva-token">Salva token e avvia la ricerca</button>'
    + '<div id="setup-msg"></div>';
  document.getElementById('salva-token').addEventListener('click', () => {
    const t = document.getElementById('token-input').value.trim();
    if (!t) {
      document.getElementById('setup-msg').innerHTML = '<div class="msg err">Incolla prima il token nel campo qui sopra.</div>';
      return;
    }
    localStorage.setItem(TOKEN_KEY, t);
    lancia(t);
  });
}

function vistaSuccesso() {
  corpo.innerHTML =
    '<div class="msg ok">✅ Ricerca avviata! I risultati appariranno qui tra qualche minuto (ricarica la pagina).</div>'
    + '<p class="nota-token">Puoi seguire il progresso su <a href="' + GH_ACTIONS_URL + '" target="_blank" rel="noopener">GitHub Actions</a>.'
    + ' · <button class="link-mini" id="cambia-token">cambia token</button></p>';
  document.getElementById('cambia-token').addEventListener('click', () => vistaSetup(''));
}

async function lancia(token) {
  corpo.innerHTML = '<div class="msg attesa">⏳ Avvio della ricerca in corso…</div>';
  let resp;
  try {
    resp = await fetch(GH_API, {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer ' + token,
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28'
      },
      body: JSON.stringify({ ref: 'main' })
    });
  } catch (e) {
    corpo.innerHTML =
      '<div class="msg err">Errore di rete: controlla la connessione a internet e riprova.</div>'
      + '<button class="azione pieno" id="riprova">Riprova</button>'
      + ' <a class="azione vuota" href="' + GH_ACTIONS_URL + '" target="_blank" rel="noopener">Avvia da GitHub →</a>';
    document.getElementById('riprova').addEventListener('click', () => lancia(token));
    return;
  }
  if (resp.status === 204) {
    vistaSuccesso();
  } else if (resp.status === 401) {
    vistaSetup('Il token non è più valido (forse è scaduto o è stato revocato). Creane uno nuovo e reincollalo qui sotto.');
  } else if (resp.status === 404 || resp.status === 403) {
    vistaSetup('GitHub non accetta questo token: probabilmente non ha accesso al repository app_interpelli o manca il permesso “Actions: Read and write”. Crea un nuovo token seguendo le istruzioni e reincollalo.');
  } else {
    vistaSetup('Errore imprevisto da GitHub (codice ' + resp.status + '). Riprova tra poco oppure usa il pulsante “Avvia da GitHub”.');
  }
}

document.getElementById('btn-lancia').addEventListener('click', () => {
  apriPannello();
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) lancia(token);
  else vistaSetup('');
});
</script>
</body>
</html>
""".replace('__DATA__', dati).replace('__AGGIORNATO__', aggiornato)
