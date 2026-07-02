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

    noti = {r.get('stable_id') for r in archivio}
    for ip in nuovi:
        if ip['stable_id'] in noti:
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
</style>
</head>
<body>
<header>
  <h1>📋 Interpelli BAT — Primaria e Infanzia</h1>
  <p>ADEE · ADAA · EEEE · AAAA — aggiornato al __AGGIORNATO__</p>
</header>
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
</script>
</body>
</html>
""".replace('__DATA__', dati).replace('__AGGIORNATO__', aggiornato)
