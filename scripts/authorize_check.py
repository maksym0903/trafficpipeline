#!/usr/bin/env python3
"""
Layer 1: Risk / authorization check — run before publish (Step 5a).

Requires config/authorized.txt (authorized=yes) or TRIAL_AUTHORIZED=1.
Validates destination + page config exist.
"""
import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trial_common import (
    AUTHORIZED_FLAG,
    CANDIDATES_TXT,
    DESTINATION_CSV,
    LOGS_DIR,
    MANIFEST_CSV,
    PAGES_CSV,
    PROJECT_ROOT,
    is_authorized,
    load_destination,
)

AUTH_LOG = os.path.join(LOGS_DIR, 'authorization.log')


def main():
    parser = argparse.ArgumentParser(description='Layer 1: authorization check before deploy')
    parser.add_argument('--require-manifest', action='store_true',
                        help='Fail if manifest.csv missing (pre-publish)')
    args = parser.parse_args()

    os.chdir(PROJECT_ROOT)
    os.makedirs(LOGS_DIR, exist_ok=True)

    errors = []
    if not is_authorized():
        errors.append(
            f'Not authorized — set authorized=yes in {AUTHORIZED_FLAG} '
            'or export TRIAL_AUTHORIZED=1 (written permission required)'
        )

    for path, label in (
        (PAGES_CSV, 'pages config'),
        (DESTINATION_CSV, 'destination config'),
        (CANDIDATES_TXT, 'candidates list'),
    ):
        if not os.path.isfile(path):
            errors.append(f'Missing {label}: {path}')

    try:
        dest = load_destination()
        if not dest.get('destination_url'):
            errors.append('destination_url empty in config/destination.csv')
    except (FileNotFoundError, ValueError) as e:
        errors.append(str(e))

    if args.require_manifest and not os.path.isfile(MANIFEST_CSV):
        errors.append(f'Manifest missing: {MANIFEST_CSV} — run Step 5 generate first')

    with open(AUTH_LOG, 'w', encoding='utf-8') as f:
        f.write(f'# authorization check {datetime.now().isoformat()}\n')
        if errors:
            for err in errors:
                f.write(f'FAIL: {err}\n')
        else:
            f.write('OK: authorized=yes destination configured\n')
            f.write(f'destination: {dest["destination_url"]}\n')

    if errors:
        print('[!] Layer 1 authorization FAILED:', file=sys.stderr)
        for err in errors:
            print(f'    - {err}', file=sys.stderr)
        print(f'    log: {AUTH_LOG}', file=sys.stderr)
        return 1

    print('[*] Layer 1: authorization OK')
    print(f'    destination: {dest["destination_url"]}')
    print(f'    log:         {AUTH_LOG}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
