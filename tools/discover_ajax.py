#!/usr/bin/env python3
"""
Strumento di discovery per siti AJAX: cattura tutte le richieste XHR fatte
dal browser reale dopo un click su un elemento, serializza URL/header/body
in JSON per analisi offline.

Uso:
    python3 tools/discover_ajax.py \
        --url "https://www.trasparenzascuole.it/Public/APDPublic_ExtV2.aspx?CF=83004410722" \
        --click '[data-action="GET_APD_TABLE"]' \
        --output tools/captures/trasparenza_83004410722.json

    python3 tools/discover_ajax.py --url "..." --headed   # mostra il browser
    python3 tools/discover_ajax.py --url "..." --no-click # solo naviga, senza click
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Playwright non installato. Esegui:")
    print("  pip install -r requirements-dev.txt")
    print("  playwright install chromium")
    sys.exit(1)

MAX_RESPONSE_BYTES = 64 * 1024  # 64 KB per response body
XHR_FILTER_KEYWORDS = ['/Ajax/', '/ajax/', '/api/', '/json', '.ashx', '.aspx?']


def _is_interesting(url: str) -> bool:
    return any(kw in url for kw in XHR_FILTER_KEYWORDS)


def run_discovery(url: str, click_selector: str | None, headed: bool, wait_after_click: float, output_path: Path) -> None:
    captures = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            locale='it-IT',
        )
        page = context.new_page()

        pending: dict[str, dict] = {}

        def on_request(request):
            if _is_interesting(request.url):
                entry = {
                    'phase': 'request',
                    'method': request.method,
                    'url': request.url,
                    'resource_type': request.resource_type,
                    'request_headers': dict(request.headers),
                    'request_body': request.post_data or '',
                    'timestamp': datetime.now().isoformat(),
                }
                pending[request.url + '|' + request.method] = entry

        def on_response(response):
            key = response.url + '|' + response.request.method
            entry = pending.pop(key, None)
            if entry is None and _is_interesting(response.url):
                entry = {
                    'phase': 'response_only',
                    'method': response.request.method,
                    'url': response.url,
                    'resource_type': response.request.resource_type,
                    'request_headers': dict(response.request.headers),
                    'request_body': response.request.post_data or '',
                    'timestamp': datetime.now().isoformat(),
                }
            if entry is not None:
                entry['status'] = response.status
                entry['response_headers'] = dict(response.headers)
                try:
                    body = response.body()
                    entry['response_body'] = body[:MAX_RESPONSE_BYTES].decode('utf-8', errors='replace')
                    entry['response_truncated'] = len(body) > MAX_RESPONSE_BYTES
                except Exception as exc:
                    entry['response_body'] = f'[errore lettura body: {exc}]'
                captures.append(entry)

        page.on('request', on_request)
        page.on('response', on_response)

        print(f"[discovery] Navigazione su: {url}")
        page.goto(url, wait_until='networkidle', timeout=30_000)
        print(f"[discovery] Pagina caricata. Richieste intercettate finora: {len(captures)}")

        if click_selector:
            print(f"[discovery] Click su: {click_selector}")
            try:
                page.click(click_selector, timeout=10_000)
            except Exception as exc:
                print(f"[discovery] ATTENZIONE: click fallito ({exc}). Continuo comunque.")
            print(f"[discovery] Attendo {wait_after_click}s per il completamento delle richieste AJAX...")
            time.sleep(wait_after_click)
            page.wait_for_load_state('networkidle', timeout=15_000)
            print(f"[discovery] Richieste totali intercettate: {len(captures)}")

        browser.close()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump({'url': url, 'captured_at': datetime.now().isoformat(), 'requests': captures}, f, ensure_ascii=False, indent=2)

    print(f"[discovery] Salvato in: {output_path}")
    print(f"[discovery] Totale richieste XHR catturate: {len(captures)}")
    for i, req in enumerate(captures, 1):
        body_preview = req.get('response_body', '')[:120].replace('\n', ' ')
        print(f"  [{i}] {req['method']} {req['url']} → {req.get('status', '?')} | body[0:120]: {body_preview!r}")


def main():
    parser = argparse.ArgumentParser(description='Playwright AJAX discovery tool')
    parser.add_argument('--url', required=True, help='URL di partenza da navigare')
    parser.add_argument('--click', dest='click_selector', default=None, help='Selettore CSS del bottone da cliccare')
    parser.add_argument('--no-click', action='store_true', help='Non fare click, solo naviga')
    parser.add_argument('--headed', action='store_true', help='Mostra il browser (default: headless)')
    parser.add_argument('--wait', type=float, default=3.0, help='Secondi da attendere dopo il click (default: 3)')
    parser.add_argument('--output', default='tools/captures/discovery.json', help='File JSON di output')
    args = parser.parse_args()

    click_sel = None if args.no_click else args.click_selector
    run_discovery(
        url=args.url,
        click_selector=click_sel,
        headed=args.headed,
        wait_after_click=args.wait,
        output_path=Path(args.output),
    )


if __name__ == '__main__':
    main()
