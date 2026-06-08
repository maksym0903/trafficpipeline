#!/usr/bin/env python3
"""
Step 5: Page generator

  candidates.txt + config/pages.csv + templates/page.html
    → output/pages/<host>/<slug>.html
    → output/manifest.csv
    → output/preview/index.html

Usage:
  python3 scripts/generate_pages.py              # all candidates × all page rows
  python3 scripts/generate_pages.py --test       # first candidate only
  python3 scripts/generate_pages.py -u URL       # single candidate
"""
import argparse
import csv
import html
import os
import re
import sys
from datetime import date
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trial_common import (
    CANDIDATES_TXT, PROJECT_ROOT, REPORT_CSV, build_baidu_head_snippet,
    load_analytics, load_candidates, load_destination, load_report,
    render_template_file, build_conversion_url,
)

OUTPUT_DIR = os.path.join(PROJECT_ROOT, 'output', 'pages')
MANIFEST_CSV = os.path.join(PROJECT_ROOT, 'output', 'manifest.csv')
PREVIEW_HTML = os.path.join(PROJECT_ROOT, 'output', 'preview', 'index.html')
PAGES_CSV = os.path.join(PROJECT_ROOT, 'config', 'pages.csv')
PAGE_TEMPLATE = os.path.join(PROJECT_ROOT, 'templates', 'page.html')
GENERATE_LOG = os.path.join(PROJECT_ROOT, 'logs', 'generate.log')


def slugify(text):
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text)
    return text.strip('-') or 'page'


def host_key(url):
    return (urlparse(url).hostname or 'unknown').replace(':', '_')


PAGE_RAW_HTML_KEYS = frozenset({'analytics_block', 'content_block', 'internal_links', 'offer_block'})


def load_page_specs(path=PAGES_CSV):
    if not os.path.isfile(path):
        raise FileNotFoundError(f'Page config not found: {path}')
    specs = []
    with open(path, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            keyword = (row.get('keyword') or '').strip()
            if not keyword or keyword.startswith('#'):
                continue
            specs.append({
                'keyword': keyword,
                'title': (row.get('title') or '').strip(),
                'meta_description': (row.get('meta_description') or '').strip(),
                'content_block': (row.get('content_block') or '').strip(),
                'internal_links': (row.get('internal_links') or '').strip(),
            })
    if not specs:
        raise ValueError(f'No page rows in {path}')
    return specs


def fill_defaults(spec):
    kw = spec['keyword']
    title = spec['title'] or kw.title()
    meta = spec['meta_description'] or f'Learn about {kw}. Guides tips and resources.'
    body = spec['content_block'] or (
        f'<p>Welcome to our guide on <strong>{html.escape(kw)}</strong>.</p>'
        f'<p>Updated {date.today().isoformat()}.</p>'
    )
    links = spec['internal_links'] or '<a href="/">Home</a>'
    return {
        'keyword': kw,
        'title': title,
        'meta_description': meta,
        'content_block': body,
        'internal_links': links,
    }


def render_page(template_path, fields, canonical_url):
    data = {**fields, 'canonical_url': canonical_url}
    return render_template_file(
        template_path, data, raw_keys=PAGE_RAW_HTML_KEYS,
    )


def deploy_path(webroot, domain_type, slug):
    base = (webroot or '/app').rstrip('/')
    return f'{base}/public/{slug}/index.html'


def generate(candidates, page_specs, report_rows, dest, template_path, out_dir, test_mode=False):
    os.makedirs(out_dir, exist_ok=True)
    manifest_rows = []
    preview_items = []
    analytics = load_analytics()
    analytics_block = (
        build_baidu_head_snippet(analytics['hm_id']) if analytics.get('enabled') else ''
    )

    for url in candidates:
        row = report_rows.get(url, {})
        webroot = row.get('webroot', '')
        domain_type = row.get('domain_type', '')
        conversion_url = build_conversion_url(dest, url)

        for spec in page_specs:
            fields = fill_defaults(spec)
            slug = slugify(fields['keyword'])
            canonical = url.rstrip('/') + '/' + slug
            fields['offer_block'] = dest.get('offer_block') or ''
            fields['analytics_block'] = analytics_block
            fields['cta_text'] = dest.get('cta_text') or 'Claim Bonus'
            fields['conversion_url'] = conversion_url
            html_doc = render_page(template_path, fields, canonical)

            rel_dir = host_key(url)
            host_out = os.path.join(out_dir, rel_dir)
            os.makedirs(host_out, exist_ok=True)
            html_file = os.path.join(host_out, f'{slug}.html')
            with open(html_file, 'w', encoding='utf-8') as f:
                f.write(html_doc)

            rel_html = os.path.relpath(html_file, PROJECT_ROOT)
            deploy = deploy_path(webroot, domain_type, slug)
            manifest_rows.append({
                'url': url,
                'keyword': fields['keyword'],
                'slug': slug,
                'title': fields['title'],
                'meta_description': fields['meta_description'],
                'canonical_url': canonical,
                'conversion_url': conversion_url,
                'cta_text': fields['cta_text'],
                'html_file': rel_html,
                'webroot': webroot,
                'domain_type': domain_type,
                'deploy_path': deploy,
            })
            preview_items.append((url, fields['title'], rel_html, canonical, conversion_url))

        if test_mode:
            break

    return manifest_rows, preview_items


def write_manifest(rows, path=MANIFEST_CSV):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fields = [
        'url', 'keyword', 'slug', 'title', 'meta_description',
        'canonical_url', 'conversion_url', 'cta_text',
        'html_file', 'webroot', 'domain_type', 'deploy_path',
    ]
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields, quoting=csv.QUOTE_ALL)
        w.writeheader()
        w.writerows(rows)


def write_preview(items, path=PREVIEW_HTML):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = [
        '<!DOCTYPE html><html><head><meta charset="utf-8">',
        '<title>Step 5 — Generated pages preview</title>',
        '<style>body{font-family:sans-serif;max-width:960px;margin:2rem auto}',
        'table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:.5rem}',
        '</style></head><body>',
        f'<h1>Generated pages ({len(items)})</h1>',
        '<table><tr><th>Target</th><th>Title</th><th>Local file</th><th>Canonical</th><th>CTA → destination</th></tr>',
    ]
    for url, title, rel_html, canonical, conversion_url in items:
        file_link = os.path.relpath(os.path.join(PROJECT_ROOT, rel_html), os.path.dirname(path))
        lines.append(
            f'<tr><td>{html.escape(url)}</td>'
            f'<td>{html.escape(title)}</td>'
            f'<td><a href="{html.escape(file_link)}">{html.escape(rel_html)}</a></td>'
            f'<td>{html.escape(canonical)}</td>'
            f'<td><a href="{html.escape(conversion_url)}">{html.escape(conversion_url)}</a></td></tr>'
        )
    lines.append('</table></body></html>')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def write_log(manifest_rows, candidates_count, page_count):
    os.makedirs(os.path.dirname(GENERATE_LOG), exist_ok=True)
    with open(GENERATE_LOG, 'w', encoding='utf-8') as f:
        f.write(f'generated={len(manifest_rows)} candidates={candidates_count} '
                f'page_specs={page_count}\n')
        for row in manifest_rows:
            f.write(f"{row['url']}\t{row['slug']}\t{row['html_file']}\n")


def main():
    parser = argparse.ArgumentParser(description='Step 5: generate pages from candidates')
    parser.add_argument('-u', '--url', help='Generate for one candidate URL only')
    parser.add_argument('--test', action='store_true', help='First candidate only')
    parser.add_argument('--pages', default=PAGES_CSV, help='Page spec CSV')
    parser.add_argument('--template', default=PAGE_TEMPLATE, help='HTML template')
    parser.add_argument('--out', default=OUTPUT_DIR, help='Output directory')
    args = parser.parse_args()

    os.chdir(PROJECT_ROOT)
    candidates = load_candidates()
    if args.url:
        if args.url not in candidates:
            print(f'[!] {args.url} not in candidates.txt', file=sys.stderr)
            sys.exit(1)
        candidates = [args.url]

    _, report_rows = load_report(require_data=True)
    page_specs = load_page_specs(args.pages)
    dest = load_destination()

    missing = [u for u in candidates if u not in report_rows]
    if missing:
        print(f'[!] {len(missing)} candidate(s) missing from report.csv', file=sys.stderr)
    no_webroot = [
        u for u in candidates
        if not report_rows.get(u, {}).get('webroot', '').strip()
    ]
    if no_webroot:
        print(
            f'[!] {len(no_webroot)} candidate(s) have no webroot in report '
            '(publish will default to /app)',
            file=sys.stderr,
        )

    manifest_rows, preview_items = generate(
        candidates, page_specs, report_rows, dest,
        args.template, args.out, test_mode=args.test,
    )

    write_manifest(manifest_rows)
    write_preview(preview_items)
    write_log(manifest_rows, len(candidates), len(page_specs))

    print(f'[*] Step 5: generated {len(manifest_rows)} page(s)')
    print(f'    pages:    {args.out}/')
    print(f'    manifest: {MANIFEST_CSV}')
    print(f'    preview:  {PREVIEW_HTML}')
    print(f'    log:      {GENERATE_LOG}')
    if args.test or args.url:
        print(f'    sample:   {manifest_rows[0]["html_file"]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
