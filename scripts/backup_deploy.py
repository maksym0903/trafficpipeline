#!/usr/bin/env python3
"""
Layer 2: Backup / rollback plan — snapshot local pages + manifest before publish.

  output/pages/ + output/manifest.csv → output/backup/<timestamp>/
"""
import argparse
import csv
import os
import shutil
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trial_common import BACKUP_DIR, LOGS_DIR, MANIFEST_CSV, OUTPUT_DIR, PROJECT_ROOT, load_manifest

BACKUP_LOG = os.path.join(LOGS_DIR, 'backup.log')


def main():
    parser = argparse.ArgumentParser(description='Layer 2: backup before publish')
    args = parser.parse_args()

    os.chdir(PROJECT_ROOT)
    os.makedirs(BACKUP_DIR, exist_ok=True)
    os.makedirs(LOGS_DIR, exist_ok=True)

    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    dest_dir = os.path.join(BACKUP_DIR, stamp)
    os.makedirs(dest_dir, exist_ok=True)

    copied = []
    manifest_src = MANIFEST_CSV
    if os.path.isfile(manifest_src):
        shutil.copy2(manifest_src, os.path.join(dest_dir, 'manifest.csv'))
        copied.append('manifest.csv')

    pages_src = os.path.join(OUTPUT_DIR, 'pages')
    if os.path.isdir(pages_src):
        shutil.copytree(pages_src, os.path.join(dest_dir, 'pages'))
        copied.append('pages/')

    snapshot = os.path.join(dest_dir, 'deploy.snapshot.csv')
    if os.path.isfile(manifest_src):
        rows = load_manifest()
        with open(snapshot, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(
                f,
                fieldnames=['url', 'slug', 'deploy_path', 'conversion_url', 'canonical_url'],
                extrasaction='ignore',
            )
            w.writeheader()
            for row in rows:
                w.writerow(row)
        copied.append('deploy.snapshot.csv')

    with open(BACKUP_LOG, 'w', encoding='utf-8') as f:
        f.write(f'backup={dest_dir}\n')
        f.write(f'timestamp={stamp}\n')
        f.write(f'items={",".join(copied)}\n')
        f.write(f'manifest_rows={len(load_manifest()) if os.path.isfile(manifest_src) else 0}\n')

    print(f'[*] Layer 2: backup saved → {dest_dir}')
    print(f'    items: {", ".join(copied) or "none"}')
    print(f'    log:   {BACKUP_LOG}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
