#!/usr/bin/env python3
"""
Step 4: Select good nodes → candidates.txt

Rules (all required):
  access=yes | webroot set | public domain | indexable=yes | traffic_value=high|medium

Optional: config/traffic.csv  or  --auto-traffic medium
"""
import argparse
import os
import subprocess
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trial_common import (
    CANDIDATES_TXT,
    LOGS_DIR,
    REPORT_CSV,
    candidate_reasons,
    is_candidate,
    load_report,
    load_traffic_overrides,
    write_candidates,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_indexable_check():
    print('[*] Step 4a: indexability check …')
    cmd = [sys.executable, 'tools/nextrce.py', '--check-indexable']
    return subprocess.call(cmd)


def select_candidates(auto_traffic='', skip_indexable=False):
    if not skip_indexable and not os.path.isfile(REPORT_CSV):
        print(f'[!] Report not found: {REPORT_CSV}', file=sys.stderr)
        return 1

    if not skip_indexable:
        rc = run_indexable_check()
        if rc != 0:
            return rc

    targets, rows = load_report(require_data=True)
    overrides = load_traffic_overrides()

    selected = []
    rejected = []
    for url in targets:
        row = rows[url]
        row['url'] = url
        reasons = candidate_reasons(row, overrides, auto_traffic)
        if reasons:
            rejected.append((url, reasons))
        else:
            selected.append(url)

    write_candidates(selected)

    os.makedirs(LOGS_DIR, exist_ok=True)
    log_path = os.path.join(LOGS_DIR, 'candidates.log')
    with open(log_path, 'w', encoding='utf-8') as f:
        f.write(f'# candidates run {datetime.now().isoformat()}\n')
        f.write(f'# selected: {len(selected)}  rejected: {len(rejected)}\n\n')
        f.write('## SELECTED\n')
        for url in selected:
            tier = rows[url].get('traffic_value') or overrides.get(url) or auto_traffic
            f.write(f'{url}\ttraffic={tier}\twebroot={rows[url].get("webroot")}\n')
        f.write('\n## REJECTED\n')
        for url, reasons in rejected:
            if rows[url].get('status') == 'success':
                f.write(f'{url}\t{",".join(reasons)}\n')

    print(f'[*] Step 4b: candidates → {CANDIDATES_TXT}')
    print(f'    selected: {len(selected)}  rejected (success): '
          f'{sum(1 for u, _ in rejected if rows[u]["status"] == "success")}')
    if not selected and not auto_traffic and not overrides:
        print('[!] traffic_value is empty for all rows.')
        print('    Add config/traffic.csv (url,traffic_value) or run with --auto-traffic medium')
    print(f'    log: {log_path}')
    return 0


def main():
    parser = argparse.ArgumentParser(description='Step 4: indexable check + candidate selection')
    parser.add_argument('--skip-indexable', action='store_true',
                        help='Skip HTTP indexability re-check')
    parser.add_argument('--auto-traffic', choices=['high', 'medium'], default='',
                        help='Treat empty traffic_value as this tier for qualifying nodes')
    parser.add_argument('--candidates-only', action='store_true',
                        help='Only run candidate selection (no indexable HTTP check)')
    args = parser.parse_args()

    os.chdir(ROOT)
    os.makedirs(os.path.join(ROOT, 'results'), exist_ok=True)
    os.makedirs(LOGS_DIR, exist_ok=True)

    if args.candidates_only:
        return select_candidates(auto_traffic=args.auto_traffic, skip_indexable=True)
    return select_candidates(auto_traffic=args.auto_traffic, skip_indexable=args.skip_indexable)


if __name__ == '__main__':
    raise SystemExit(main())
