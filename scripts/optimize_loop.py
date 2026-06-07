#!/usr/bin/env python3
"""
Step 10: Optimization loop — promote high performers in traffic.csv and refresh candidates.

Uses Step 8 traffic_report.csv to set real tiers, then re-runs candidate selection.
"""
import argparse
import csv
import os
import subprocess
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trial_common import (
    LOGS_DIR,
    PROJECT_ROOT,
    TRAFFIC_OVERRIDES,
    TRAFFIC_REPORT_CSV,
)

OPT_LOG = os.path.join(LOGS_DIR, 'optimize.log')


def tier_from_row(row):
    try:
        hits = int(row.get('server_log_hits') or 0)
        conv = int(row.get('conversion_clicks') or 0)
        gsc = int(row.get('gsc_clicks') or 0)
    except ValueError:
        return ''
    score = hits + conv * 5 + gsc
    if score >= 100 or conv >= 5:
        return 'high'
    if score >= 10 or conv >= 1 or hits >= 20:
        return 'medium'
    return 'low'


def update_traffic_csv(path=TRAFFIC_REPORT_CSV, out=TRAFFIC_OVERRIDES):
    if not os.path.isfile(path):
        print(f'[!] No traffic report: {path}', file=sys.stderr)
        return 0

    tiers = {}
    with open(path, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            tier = tier_from_row(row)
            if tier in ('high', 'medium'):
                tiers[row['url']] = tier

    os.makedirs(os.path.dirname(out), exist_ok=True)
    lines = ['url,traffic_value', '# Auto-updated by Step 10 optimize_loop.py']
    for url, tier in sorted(tiers.items()):
        lines.append(f'{url},{tier}')
    with open(out, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    return len(tiers)


def main():
    parser = argparse.ArgumentParser(description='Step 10: optimization loop')
    args = parser.parse_args()

    os.chdir(PROJECT_ROOT)
    os.makedirs(LOGS_DIR, exist_ok=True)

    promoted = update_traffic_csv()
    rc = subprocess.call([
        sys.executable, 'scripts/check_nodes.py',
        '--candidates-only', '--skip-indexable',
    ])

    with open(OPT_LOG, 'w', encoding='utf-8') as f:
        f.write(f'# optimize {datetime.now().isoformat()}\n')
        f.write(f'promoted_tiers={promoted}\n')
        f.write(f'candidate_refresh_rc={rc}\n')

    print(f'[*] Step 10: optimization loop')
    print(f'    promoted in traffic.csv: {promoted}')
    print(f'    candidates refreshed (rc={rc})')
    print(f'    log: {OPT_LOG}')
    return rc


if __name__ == '__main__':
    raise SystemExit(main())
