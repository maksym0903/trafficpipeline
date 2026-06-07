#!/usr/bin/env python3
"""
Step 1–2: URL list → scan → enrich → report.csv / success.txt / failed.txt
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET_LIST = os.path.join(ROOT, 'urls', 'target.txt')


def main():
    os.chdir(ROOT)
    os.makedirs(os.path.join(ROOT, 'results'), exist_ok=True)
    os.makedirs(os.path.join(ROOT, 'logs'), exist_ok=True)

    if not os.path.isfile(TARGET_LIST):
        print(f'[!] Target list not found: {TARGET_LIST}', file=sys.stderr)
        sys.exit(1)

    cmd = [
        sys.executable, 'tools/nextrce.py',
        '-l', TARGET_LIST,
        '-o', 'results/success.txt',
        *sys.argv[1:],
    ]
    print('[*] Step 1–2: scan + enrich + report …')
    raise SystemExit(subprocess.call(cmd))


if __name__ == '__main__':
    main()
