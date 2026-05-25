import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _run_metadata() -> Dict:
    run_id = os.environ.get('GITHUB_RUN_ID', '')
    server = os.environ.get('GITHUB_SERVER_URL', 'https://github.com')
    repo = os.environ.get('GITHUB_REPOSITORY', '')
    url = f"{server}/{repo}/actions/runs/{run_id}" if run_id and repo else None
    return {
        'number': os.environ.get('GITHUB_RUN_NUMBER', 'local'),
        'id': run_id,
        'attempt': os.environ.get('GITHUB_RUN_ATTEMPT', '1'),
        'event': os.environ.get('GITHUB_EVENT_NAME', 'manual'),
        'url': url,
        'started_at': datetime.now().isoformat(),
        'ended_at': None,
    }


class RunReporter:
    def __init__(self):
        self._meta = _run_metadata()
        self._notified: List[Dict] = []
        self._already_seen: List[Dict] = []
        self._expired: List[Dict] = []
        self._wrong_codes: List[Dict] = []

    def record_rejected(self, interpello: Dict, reason: str, source: str):
        record = self._make_record(interpello, 'wrong_codes')
        record['rejection_reason'] = reason
        record['source'] = source
        self._wrong_codes.append(record)

    def record_expired(self, interpello: Dict):
        self._expired.append(self._make_record(interpello, 'expired'))

    def record_already_seen(self, interpello: Dict):
        self._already_seen.append(self._make_record(interpello, 'already_seen'))

    def record_notified(self, interpello: Dict):
        self._notified.append(self._make_record(interpello, 'notified'))

    def _make_record(self, interpello: Dict, status: str) -> Dict:
        return {
            'status': status,
            'source': interpello.get('source', ''),
            'title': interpello.get('title', ''),
            'link': interpello.get('link', ''),
            'tipo': interpello.get('tipo', ''),
            'scadenza': interpello.get('scadenza', ''),
            'stable_id': interpello.get('stable_id', ''),
            'data_rilevamento': interpello.get('data_rilevamento', ''),
            'testo': (interpello.get('testo') or '')[:500],
        }

    def _build_data(self) -> Dict:
        all_records = self._notified + self._already_seen + self._expired + self._wrong_codes
        by_source: Dict[str, int] = {}
        for r in all_records:
            src = r.get('source', 'unknown')
            by_source[src] = by_source.get(src, 0) + 1
        return {
            'run': self._meta,
            'summary': {
                'fetched_total': len(all_records),
                'notified': len(self._notified),
                'already_seen': len(self._already_seen),
                'expired': len(self._expired),
                'wrong_codes': len(self._wrong_codes),
                'by_source': by_source,
            },
            'notified': self._notified,
            'already_seen': self._already_seen,
            'expired': self._expired,
            'wrong_codes': self._wrong_codes,
        }

    def write(self, reports_dir: Path) -> Tuple[Path, Path]:
        self._meta['ended_at'] = datetime.now().isoformat()
        reports_dir = Path(reports_dir)
        reports_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.fromisoformat(self._meta['started_at']).strftime('%Y%m%d-%H%M%S')
        run_num = self._meta.get('number', 'local')
        base = f"run-{run_num}-{ts}"

        data = self._build_data()
        json_path = reports_dir / f"{base}.json"
        md_path = reports_dir / f"{base}.md"

        json_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8'
        )
        md_path.write_text(self._build_md(data), encoding='utf-8')
        self._update_index(reports_dir)

        return json_path, md_path

    def _build_md(self, data: Dict) -> str:
        meta = data['run']
        summary = data['summary']
        run_label = f"#{meta['number']}" if meta['number'] != 'local' else 'local'
        run_link = f"[workflow run]({meta['url']})" if meta['url'] else 'n/a'
        started = (meta.get('started_at') or '')[:19].replace('T', ' ')
        ended = (meta.get('ended_at') or '')[:19].replace('T', ' ')

        lines = [
            f"# Report Interpelli — Run {run_label}",
            '',
            '## Riepilogo',
            '',
            '| Campo | Valore |',
            '|-------|--------|',
            f"| Run | {run_label} ({meta.get('event', '')}) |",
            f"| Link | {run_link} |",
            f"| Inizio | {started} |",
            f"| Fine | {ended} |",
            f"| Notificati | {summary['notified']} |",
            f"| Già visti (dedup) | {summary['already_seen']} |",
            f"| Scaduti | {summary['expired']} |",
            f"| Codici non target | {summary['wrong_codes']} |",
            '',
        ]

        def table(items: List[Dict], empty_msg: str) -> List[str]:
            if not items:
                return [f'_{empty_msg}_', '']
            rows = [
                '| Source | Tipo | Scadenza | Titolo | Link |',
                '|--------|------|----------|--------|------|',
            ]
            for r in items:
                title = (r.get('title') or '')[:80].replace('|', '\\|')
                link = r.get('link') or ''
                link_cell = f"[link]({link})" if link else '—'
                scadenza = r.get('scadenza') or 'Non specificata'
                tipo = r.get('tipo') or ''
                src = r.get('source') or ''
                rows.append(f"| {src} | {tipo} | {scadenza} | {title} | {link_cell} |")
            rows.append('')
            return rows

        lines += ['## Notificati', '']
        lines += table(data['notified'], 'Nessuno')

        lines += ['## Già visti (dedup)', '']
        lines += table(data['already_seen'], 'Nessuno')

        lines += ['## Scaduti', '']
        lines += table(data['expired'], 'Nessuno')

        lines += ['## Codici non target (vicini al match)', '']
        lines += table(data['wrong_codes'], 'Nessuno')

        return '\n'.join(lines)

    def _update_index(self, reports_dir: Path):
        json_files = sorted(reports_dir.glob('run-*.json'), reverse=True)
        rows = []
        for jf in json_files[:200]:
            try:
                d = json.loads(jf.read_text(encoding='utf-8'))
                m = d['run']
                s = d['summary']
                run_label = f"#{m['number']}" if m.get('number') != 'local' else 'local'
                started = (m.get('started_at') or '')[:16].replace('T', ' ')
                event = m.get('event', '')
                notified = s.get('notified', 0)
                rejected_total = s.get('already_seen', 0) + s.get('expired', 0) + s.get('wrong_codes', 0)
                md_file = jf.stem + '.md'
                rows.append(
                    f"| {run_label} | {started} | {event} | {notified} | {rejected_total} "
                    f"| [JSON]({jf.name}) · [MD]({md_file}) |"
                )
            except Exception:
                continue

        content = '\n'.join([
            '# Index Report Interpelli',
            '',
            '| Run | Data | Evento | Notificati | Scartati totali | File |',
            '|-----|------|--------|------------|-----------------|------|',
        ] + rows + [''])
        (reports_dir / 'INDEX.md').write_text(content, encoding='utf-8')


def prune_old_reports(reports_dir: Path, keep_days: int = 60):
    cutoff = datetime.now() - timedelta(days=keep_days)
    for jf in Path(reports_dir).glob('run-*.json'):
        parts = jf.stem.split('-', 2)  # ['run', number, 'YYYYMMDD-HHMMSS']
        if len(parts) < 3:
            continue
        try:
            ts = datetime.strptime(parts[2], '%Y%m%d-%H%M%S')
        except ValueError:
            continue
        if ts < cutoff:
            jf.unlink(missing_ok=True)
            md = jf.with_suffix('.md')
            if md.exists():
                md.unlink()
