#!/usr/bin/env python3
"""
Backfill una tantum della dashboard: raccoglie tutti gli interpelli notificati
dai report storici (reports/run-*.json), risolve le scadenze mancanti seguendo
i link (pagine, PDF, API Argo), marca come archiviati gli atti Argo non più in
pubblicazione, e rigenera docs/interpelli.json + docs/index.html.

Uso:  python3 tools/backfill_dashboard.py
"""
import glob
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dashboard import aggiorna_dashboard
from link_resolver import risolvi_scadenza_da_link, argo_archiviato


def main():
    records = {}
    for f in sorted(glob.glob('reports/run-*.json')):
        try:
            d = json.load(open(f, encoding='utf-8'))
        except Exception:
            continue
        for r in d.get('notified', []):
            sid = r.get('stable_id')
            if sid and sid not in records:
                records[sid] = r

    recs = list(records.values())
    print(f"Interpelli storici trovati nei report: {len(recs)}")

    da_risolvere = [r for r in recs if not r.get('scadenza') and r.get('link')]
    print(f"Da risolvere via link/PDF/API: {len(da_risolvere)}")
    for i, r in enumerate(da_risolvere, 1):
        scad = risolvi_scadenza_da_link(r['link'])
        if scad:
            r['scadenza'] = scad
            print(f"  [{i}/{len(da_risolvere)}] ✓ {scad} ← {r.get('title', '')[:60]}")
        elif 'portaleargo.it' in (r['link'] or '') and argo_archiviato(r['link']):
            r['archiviato'] = True
            print(f"  [{i}/{len(da_risolvere)}] 🗄 archiviato ← {r.get('title', '')[:60]}")
        else:
            print(f"  [{i}/{len(da_risolvere)}] — non risolto ← {r.get('title', '')[:60]}")
        time.sleep(0.3)

    aggiorna_dashboard(recs, dry_run=False)


if __name__ == '__main__':
    main()
