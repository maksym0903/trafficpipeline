#!/usr/bin/env python3
"""
Layer 3: Client result report — aggregate pipeline deliverables after Step 8.

Metrics:
  1. usable_nodes_count       (access=yes)
  2. deployable_domains_count (candidates)
  3. published_page_count     (published.txt)
  4. indexed_page_count       (indexing ready + partial)
  5. page_views                 (sum page_views)
  6. unique_visitors            (sum unique_visitors)
  7. conversion_landing_clicks  (sum conversion_clicks → destination)
  8. unique_converters          (sum unique_converters)
"""
import argparse
import csv
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trial_common import (
    CANDIDATES_TXT,
    CLIENT_REPORT_CSV,
    CLIENT_REPORT_HTML,
    INDEXED_TXT,
    INDEXING_CSV,
    LOGS_DIR,
    PROJECT_ROOT,
    PUBLISHED_TXT,
    TRAFFIC_REPORT_CSV,
    load_candidates,
    load_destination,
    load_published,
    load_report,
)

REPORT_LOG = os.path.join(LOGS_DIR, 'client_report.log')

METRICS = [
    ('usable_nodes_count', 'Nodes with RCE access (access=yes)'),
    ('deployable_domains_count', 'Domains passing candidate rules'),
    ('published_page_count', 'Traffic pages published to nodes'),
    ('indexed_page_count', 'Pages indexed or partially indexed'),
    ('page_views', 'Total HTML page views across published sites'),
    ('unique_visitors', 'Unique visitor IPs across published sites'),
    ('conversion_landing_clicks', 'Claim Bonus landings on destination (liumen26)'),
    ('unique_converters', 'Unique IPs that reached destination'),
]


def count_indexed(path=INDEXING_CSV):
    if not os.path.isfile(path):
        return 0
    count = 0
    with open(path, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            if row.get('index_status') in ('ready', 'partial'):
                count += 1
    return count


def sum_traffic_column(path, column):
    if not os.path.isfile(path):
        return 0
    total = 0
    with open(path, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            try:
                total += int(row.get(column) or 0)
            except ValueError:
                pass
    return total


def collect_metrics():
    _, report_rows = load_report(require_data=False)
    usable = sum(1 for r in report_rows.values() if r.get('access') == 'yes')

    deployable = 0
    if os.path.isfile(CANDIDATES_TXT):
        deployable = len(load_candidates())

    published = len(load_published())
    indexed = count_indexed()
    if indexed == 0 and os.path.isfile(INDEXED_TXT):
        indexed = len(load_published(INDEXED_TXT))

    traffic_clicks = sum_traffic_column(TRAFFIC_REPORT_CSV, 'page_views')
    unique_visitors = sum_traffic_column(TRAFFIC_REPORT_CSV, 'unique_visitors')
    conversion_clicks = sum_traffic_column(TRAFFIC_REPORT_CSV, 'conversion_clicks')
    unique_converters = sum_traffic_column(TRAFFIC_REPORT_CSV, 'unique_converters')

    return {
        'usable_nodes_count': usable,
        'deployable_domains_count': deployable,
        'published_page_count': published,
        'indexed_page_count': indexed,
        'page_views': traffic_clicks,
        'unique_visitors': unique_visitors,
        'conversion_landing_clicks': conversion_clicks,
        'unique_converters': unique_converters,
    }


def write_csv(metrics, path=CLIENT_REPORT_CSV):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['metric', 'value', 'description'])
        for key, desc in METRICS:
            w.writerow([key, metrics[key], desc])


def write_html(metrics, path=CLIENT_REPORT_HTML):
    try:
        dest = load_destination()
        destination = dest['destination_url']
    except (FileNotFoundError, ValueError):
        destination = '(not configured)'

    rows_html = []
    for key, desc in METRICS:
        rows_html.append(
            f'<tr><td>{key}</td><td><strong>{metrics[key]}</strong></td><td>{desc}</td></tr>'
        )
    html = f'''<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Client Result Report</title>
<style>body{{font-family:sans-serif;max-width:720px;margin:2rem auto}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ccc;padding:.5rem}}</style>
</head><body>
<h1>Pipeline Result Report</h1>
<p>Generated {datetime.now().isoformat(timespec="seconds")}</p>
<p>Destination funnel: <code>{destination}</code></p>
<table><tr><th>Metric</th><th>Value</th><th>Description</th></tr>
{"".join(rows_html)}
</table>
</body></html>'''
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)


def main():
    parser = argparse.ArgumentParser(description='Layer 3: client result report')
    args = parser.parse_args()

    os.chdir(PROJECT_ROOT)
    os.makedirs(LOGS_DIR, exist_ok=True)

    metrics = collect_metrics()
    write_csv(metrics)
    write_html(metrics)

    with open(REPORT_LOG, 'w', encoding='utf-8') as f:
        f.write(f'# client report {datetime.now().isoformat()}\n')
        for key, _ in METRICS:
            f.write(f'{key}={metrics[key]}\n')

    print('[*] Layer 3: client result report')
    for key, desc in METRICS:
        print(f'    {key}: {metrics[key]}  ({desc})')
    print(f'    csv:  {CLIENT_REPORT_CSV}')
    print(f'    html: {CLIENT_REPORT_HTML}')
    print(f'    log:  {REPORT_LOG}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
