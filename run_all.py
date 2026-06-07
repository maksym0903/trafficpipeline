#!/usr/bin/env python3
"""Cross-platform entry point for the full pipeline (Windows-friendly)."""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))


def run(cmd, check=True):
    print(f'[*] {" ".join(cmd)}')
    return subprocess.run(cmd, cwd=ROOT, check=check)


def first_candidate():
    path = os.path.join(ROOT, 'results', 'candidates.txt')
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        print('[!] results/candidates.txt is empty — run Steps 1–4 first', file=sys.stderr)
        sys.exit(1)
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                return line
    print('[!] results/candidates.txt has no candidate URLs', file=sys.stderr)
    sys.exit(1)


def step(title):
    print()
    print('=' * 60)
    print(f'  {title}')
    print('=' * 60)


def main():
    parser = argparse.ArgumentParser(description='Run all pipeline steps (cross-platform)')
    parser.add_argument('--test', action='store_true', help='Steps 5–8 on first candidate only')
    parser.add_argument('--skip-scan', action='store_true', help='Start from Step 3 using report.csv')
    parser.add_argument('--from-step', type=int, default=1, metavar='N')
    parser.add_argument('scan_args', nargs=argparse.REMAINDER,
                        help='Extra args forwarded to build_report.py (Step 1–2)')
    args = parser.parse_args()

    os.makedirs(os.path.join(ROOT, 'results'), exist_ok=True)
    os.makedirs(os.path.join(ROOT, 'logs'), exist_ok=True)
    os.makedirs(os.path.join(ROOT, 'output', 'backup'), exist_ok=True)

    py = sys.executable
    from_step = args.from_step

    if from_step <= 2 and not args.skip_scan:
        step('Step 1–2: Scan + enrich → report.csv')
        run([py, 'scripts/build_report.py'] + args.scan_args)

    if from_step <= 3:
        step('Step 3: Classify nodes → results/*.txt')
        run([py, 'scripts/classify_nodes.py'])

    if from_step <= 4:
        step('Step 4: Select candidates → candidates.txt')
        run([py, 'scripts/check_nodes.py', '--auto-traffic', 'medium'])

    if from_step <= 5:
        step('Step 5: Generate bridge pages → output/pages/')
        gen_cmd = [py, 'scripts/generate_pages.py']
        if args.test:
            gen_cmd.append('--test')
        run(gen_cmd)

    if from_step <= 6:
        step('Step 5a: Authorization check (Layer 1)')
        run([py, 'scripts/authorize_check.py', '--require-manifest'])
        step('Step 5b: Backup / rollback plan (Layer 2)')
        run([py, 'scripts/backup_deploy.py'])

    if from_step <= 6:
        step('Step 6: Publish pages → remote nodes')
        pub_cmd = [py, 'scripts/publish_pages.py']
        if args.test:
            pub_cmd.extend(['--test', '-u', first_candidate()])
        run(pub_cmd, check=False)

    if from_step <= 7:
        step('Step 7: Indexing verify + ping')
        idx_cmd = [py, 'scripts/index_pages.py']
        if args.test:
            idx_cmd.extend(['--test', '-u', first_candidate()])
        else:
            idx_cmd.append('--published-only')
        run(idx_cmd)

    if from_step <= 8:
        step('Step 8: Traffic tracking → traffic_report.csv')
        tr_cmd = [py, 'scripts/track_traffic.py']
        if args.test:
            tr_cmd.extend(['--test', '-u', first_candidate()])
        else:
            tr_cmd.append('--published-only')
        run(tr_cmd)

    step('Step 9: Client result report (Layer 3)')
    run([py, 'scripts/result_report.py'])

    step('Step 10: Optimization loop')
    run([py, 'scripts/optimize_loop.py'], check=False)

    print()
    print('=' * 60)
    print('  PIPELINE COMPLETE')
    print('=' * 60)
    print('  client report:  results/client_report.csv')
    print('  traffic:        results/traffic_report.csv')
    print('  published:      results/published.txt')


if __name__ == '__main__':
    raise SystemExit(main())
