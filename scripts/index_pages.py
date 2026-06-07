#!/usr/bin/env python3
"""
Step 7: Indexing — verify sitemap, robots, canonical + ping search engines.

  manifest.csv (+ optional published.txt) → results/indexing.csv + indexed.txt

Checks (public HTTP):
  - /sitemap.xml contains page URL
  - /robots.txt references sitemap
  - page has correct rel=canonical
  - ping Google + Bing sitemap endpoints

Manual GSC/Bing links → results/submit_links.txt

Usage:
  python3 scripts/index_pages.py --test -u https://example.com
  python3 scripts/index_pages.py --published-only
  python3 scripts/index_pages.py
"""
import argparse
import csv
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trial_common import (
    INDEXED_TXT,
    INDEXING_CSV,
    LOGS_DIR,
    MANIFEST_CSV,
    PROJECT_ROOT,
    http_fetch,
    load_manifest,
    load_published,
    normalize_url,
)

INDEXING_LOG = os.path.join(LOGS_DIR, 'indexing.log')
SUBMIT_LINKS = os.path.join(PROJECT_ROOT, 'results', 'submit_links.txt')

INDEXING_COLUMNS = [
    'url', 'page_url', 'sitemap_url', 'sitemap_ok', 'robots_ok',
    'canonical_ok', 'google_ping', 'bing_ping', 'index_status', 'notes',
]

GOOGLE_PING = 'https://www.google.com/ping?sitemap='
BING_PING = 'https://www.bing.com/ping?sitemap='


def site_base(url):
    return url.rstrip('/')


def sitemap_public_url(base):
    return f'{base}/sitemap.xml'


def robots_public_url(base):
    return f'{base}/robots.txt'


def check_sitemap(sitemap_url, page_url, timeout=15):
    try:
        status, body, _ = http_fetch(sitemap_url, timeout)
    except (HTTPError, URLError, OSError) as e:
        return False, str(e)
    if status != 200:
        return False, f'http_{status}'
    if page_url in body or normalize_url(page_url) in normalize_url(body):
        return True, 'ok'
    path = urlparse_path(page_url)
    if path and path in body:
        return True, 'ok_path'
    return False, 'page_not_in_sitemap'


def urlparse_path(page_url):
    from urllib.parse import urlparse
    return urlparse(page_url).path


def check_robots(robots_url, sitemap_url, timeout=15):
    try:
        status, body, _ = http_fetch(robots_url, timeout)
    except (HTTPError, URLError, OSError) as e:
        return False, str(e)
    if status != 200:
        return False, f'http_{status}'
    lower = body.lower()
    if 'disallow: /' in lower and 'allow:' not in lower:
        return False, 'disallow_all'
    if 'sitemap:' not in lower:
        return False, 'no_sitemap_line'
    return True, 'ok'


def check_canonical(page_url, expected_canonical, timeout=15):
    try:
        status, body, _ = http_fetch(page_url, timeout)
    except (HTTPError, URLError, OSError) as e:
        return False, str(e)
    if status != 200:
        return False, f'http_{status}'
    patterns = [
        r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']',
        r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']canonical["\']',
    ]
    for pat in patterns:
        m = re.search(pat, body, re.I)
        if m:
            found = normalize_url(m.group(1))
            if found == normalize_url(expected_canonical):
                return True, 'ok'
            return False, f'mismatch:{m.group(1)}'
    return False, 'no_canonical_tag'


def ping_engine(ping_base, sitemap_url, timeout=15):
    try:
        status, body, _ = http_fetch(ping_base + quote(sitemap_url, safe=''), timeout)
        if status in (200, 204):
            return True, 'ok'
        return False, f'http_{status}'
    except (HTTPError, URLError, OSError) as e:
        return False, str(e)


def index_one(row, do_ping=True, timeout=15):
    base = site_base(row['url'])
    page_url = row.get('canonical_url') or f"{base}/{row['slug']}"
    sitemap_url = sitemap_public_url(base)
    robots_url = robots_public_url(base)
    notes = []

    sitemap_ok, sitemap_note = check_sitemap(sitemap_url, page_url, timeout)
    if sitemap_note != 'ok':
        notes.append(f'sitemap:{sitemap_note}')

    robots_ok, robots_note = check_robots(robots_url, sitemap_url, timeout)
    if robots_note != 'ok':
        notes.append(f'robots:{robots_note}')

    canonical_ok, canon_note = check_canonical(page_url, page_url, timeout)
    if canon_note != 'ok':
        notes.append(f'canonical:{canon_note}')

    google_ping, google_note = 'skip', 'skip'
    bing_ping, bing_note = 'skip', 'skip'
    if do_ping and sitemap_ok:
        g_ok, google_note = ping_engine(GOOGLE_PING, sitemap_url, timeout)
        google_ping = 'yes' if g_ok else 'no'
        if not g_ok:
            notes.append(f'google:{google_note}')
        b_ok, bing_note = ping_engine(BING_PING, sitemap_url, timeout)
        bing_ping = 'yes' if b_ok else 'no'
        if not b_ok:
            notes.append(f'bing:{bing_note}')

    core_ok = sitemap_ok and robots_ok and canonical_ok
    if core_ok and (google_ping in ('yes', 'skip') and bing_ping in ('yes', 'skip')):
        status = 'ready'
    elif sitemap_ok or robots_ok or canonical_ok:
        status = 'partial'
    else:
        status = 'fail'

    return {
        'url': row['url'],
        'page_url': page_url,
        'sitemap_url': sitemap_url,
        'sitemap_ok': 'yes' if sitemap_ok else 'no',
        'robots_ok': 'yes' if robots_ok else 'no',
        'canonical_ok': 'yes' if canonical_ok else 'no',
        'google_ping': google_ping,
        'bing_ping': bing_ping,
        'index_status': status,
        'notes': ' | '.join(notes),
    }


def write_indexing_csv(rows, path=INDEXING_CSV):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=INDEXING_COLUMNS, quoting=csv.QUOTE_ALL)
        w.writeheader()
        w.writerows(rows)


def write_indexed(rows, path=INDEXED_TXT):
    ready = [r['url'] for r in rows if r['index_status'] == 'ready']
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        for url in ready:
            f.write(url + '\n')
    return ready


def write_submit_links(rows, path=SUBMIT_LINKS):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('# Manual Search Console / Bing Webmaster submission links\n')
        for row in rows:
            base = site_base(row['url'])
            enc = quote(base, safe='')
            f.write(f"\n# {row['url']}  status={row['index_status']}\n")
            f.write(f"GSC: https://search.google.com/search-console?resource_id={enc}\n")
            f.write(f"Bing: https://www.bing.com/webmasters/home?siteUrl={enc}\n")
            f.write(f"Sitemap: {row['sitemap_url']}\n")
            f.write(f"Page: {row['page_url']}\n")


def write_log(rows):
    os.makedirs(os.path.dirname(INDEXING_LOG), exist_ok=True)
    with open(INDEXING_LOG, 'w', encoding='utf-8') as f:
        for row in rows:
            f.write(
                f"{row['index_status']}\t{row['url']}\t"
                f"sitemap={row['sitemap_ok']} robots={row['robots_ok']} "
                f"canonical={row['canonical_ok']} "
                f"google={row['google_ping']} bing={row['bing_ping']}\n"
            )
            if row['notes']:
                f.write(f"  {row['notes']}\n")


def filter_manifest(rows, published_only=False, url_filter=None, test=False):
    if published_only:
        published = set(load_published())
        if published:
            rows = [r for r in rows if r['url'] in published]
    if url_filter:
        rows = [r for r in rows if r['url'] == url_filter]
    if test:
        rows = rows[:1]
    return rows


def main():
    parser = argparse.ArgumentParser(description='Step 7: indexing verify + ping')
    parser.add_argument('-u', '--url', help='Check one manifest URL')
    parser.add_argument('--test', action='store_true', help='First row only')
    parser.add_argument('--published-only', action='store_true',
                        help='Only URLs in results/published.txt')
    parser.add_argument('--no-ping', action='store_true',
                        help='Skip Google/Bing sitemap ping')
    parser.add_argument('-t', '--threads', type=int, default=5)
    parser.add_argument('--timeout', type=int, default=15)
    args = parser.parse_args()

    os.chdir(PROJECT_ROOT)
    rows = filter_manifest(
        load_manifest(),
        published_only=args.published_only,
        url_filter=args.url,
        test=args.test,
    )
    if not rows:
        print('[!] No rows to index-check', file=sys.stderr)
        return 1

    print(f'[*] Step 7: indexing check for {len(rows)} site(s) …')
    do_ping = not args.no_ping

    def _job(row):
        return index_one(row, do_ping=do_ping, timeout=args.timeout)

    workers = min(args.threads, len(rows))
    if workers <= 1:
        results = [_job(r) for r in rows]
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(_job, rows))

    write_indexing_csv(results)
    ready = write_indexed(results)
    write_submit_links(results)
    write_log(results)

    counts = {}
    for r in results:
        counts[r['index_status']] = counts.get(r['index_status'], 0) + 1

    print(f'[*] ready={counts.get("ready", 0)} partial={counts.get("partial", 0)} '
          f'fail={counts.get("fail", 0)}')
    print(f'    report:  {INDEXING_CSV}')
    print(f'    indexed: {INDEXED_TXT} ({len(ready)} URLs)')
    print(f'    GSC/Bing links: {SUBMIT_LINKS}')
    print(f'    log:     {INDEXING_LOG}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
