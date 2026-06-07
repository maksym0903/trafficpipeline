"""Shared paths and report helpers for the trial pipeline."""
import csv
import html
import os
import re
import ssl
from urllib.parse import urlparse, urljoin, quote, urlencode
from urllib.request import Request, HTTPSHandler, build_opener

TEMPLATE_PLACEHOLDER_RE = re.compile(r'\{\{(\w+)\}\}')

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(PROJECT_ROOT, 'config')
RESULTS_DIR = os.path.join(PROJECT_ROOT, 'results')
OUTPUT_DIR = os.path.join(PROJECT_ROOT, 'output')
LOGS_DIR = os.path.join(PROJECT_ROOT, 'logs')
URLS_DIR = os.path.join(PROJECT_ROOT, 'urls')
TEMPLATES_DIR = os.path.join(PROJECT_ROOT, 'templates')

REPORT_CSV = os.path.join(RESULTS_DIR, 'report.csv')
CANDIDATES_TXT = os.path.join(RESULTS_DIR, 'candidates.txt')
MANIFEST_CSV = os.path.join(OUTPUT_DIR, 'manifest.csv')
PUBLISHED_TXT = os.path.join(RESULTS_DIR, 'published.txt')
INDEXING_CSV = os.path.join(RESULTS_DIR, 'indexing.csv')
INDEXED_TXT = os.path.join(RESULTS_DIR, 'indexed.txt')
TRAFFIC_REPORT_CSV = os.path.join(RESULTS_DIR, 'traffic_report.csv')
TRACKING_TXT = os.path.join(RESULTS_DIR, 'tracking.txt')
TRAFFIC_OVERRIDES = os.path.join(CONFIG_DIR, 'traffic.csv')
TRACKING_MANUAL = os.path.join(CONFIG_DIR, 'tracking_manual.csv')
PAGES_CSV = os.path.join(CONFIG_DIR, 'pages.csv')
DESTINATION_CSV = os.path.join(CONFIG_DIR, 'destination.csv')
AUTHORIZED_FLAG = os.path.join(CONFIG_DIR, 'authorized.txt')
CLIENT_REPORT_CSV = os.path.join(RESULTS_DIR, 'client_report.csv')
CLIENT_REPORT_HTML = os.path.join(RESULTS_DIR, 'client_report.html')
BACKUP_DIR = os.path.join(OUTPUT_DIR, 'backup')

def ssl_verify_enabled():
    """Return True when TRIAL_SSL_VERIFY is set to 1/true/yes (default: off)."""
    return os.environ.get('TRIAL_SSL_VERIFY', '0').lower() in ('1', 'true', 'yes')


def make_ssl_context():
    ctx = ssl.create_default_context()
    if not ssl_verify_enabled():
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


_SSL = make_ssl_context()
_HTTP_OPENER = build_opener(HTTPSHandler(context=_SSL))
_USER_AGENT = 'Mozilla/5.0 (compatible; TrialIndexer/1.0)'

REPORT_COLUMNS = [
    'url', 'status', 'access', 'user', 'hostname', 'os', 'nodejs', 'docker',
    'webroot', 'domain_type', 'traffic_value', 'notes', 'indexable',
]

DEV_HOST_MARKERS = (
    '-dev.', '-uat.', '-staging.', '.staging.', 'az-dev.', '-test.', '.local',
)

VALID_TRAFFIC = frozenset({'high', 'medium'})


def load_report(csv_path=REPORT_CSV, *, require_data=False):
    if not os.path.isfile(csv_path):
        raise FileNotFoundError(f'Report not found: {csv_path}')
    targets = []
    rows = {}
    with open(csv_path, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            url = row['url']
            targets.append(url)
            rows[url] = {col: row.get(col, '') for col in REPORT_COLUMNS if col != 'url'}
    if require_data and not targets:
        raise ValueError(
            f'Report has no scan rows: {csv_path} — run ./scan or '
            'python3 scripts/build_report.py first'
        )
    return targets, rows


def load_traffic_overrides(path=TRAFFIC_OVERRIDES):
    """Optional config/traffic.csv: url,traffic_value (high|medium)."""
    overrides = {}
    if not os.path.isfile(path):
        return overrides
    with open(path, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            url = (row.get('url') or '').strip()
            if not url or url.startswith('#'):
                continue
            tier = (row.get('traffic_value') or '').strip().lower()
            if url and tier in VALID_TRAFFIC:
                overrides[url] = tier
    return overrides


def is_public_domain(url):
    host = (urlparse(url).hostname or '').lower()
    if not host or host == 'localhost':
        return False
    if re.match(r'^\d+\.\d+\.\d+\.\d+$', host):
        return False
    if '.' not in host:
        return False
    if any(marker in host for marker in DEV_HOST_MARKERS):
        return False
    return True


def effective_traffic(row, overrides=None, auto_traffic=''):
    tier = row.get('traffic_value', '').strip().lower()
    if tier in VALID_TRAFFIC:
        return tier
    if overrides and row['url'] in overrides:
        return overrides[row['url']]
    if auto_traffic in VALID_TRAFFIC:
        return auto_traffic
    return ''


def candidate_reasons(row, overrides=None, auto_traffic=''):
    if row.get('status') != 'success':
        return ['not_success']
    if row.get('access') != 'yes':
        return ['access!=yes']
    if not row.get('webroot', '').strip():
        return ['no_webroot']
    if row.get('indexable') != 'yes':
        return ['not_indexable']
    if not is_public_domain(row['url']):
        return ['not_public_domain']
    tier = effective_traffic(row, overrides, auto_traffic)
    if tier not in VALID_TRAFFIC:
        return [f'traffic_value={row.get("traffic_value") or "empty"}']
    return []


def is_candidate(row, overrides=None, auto_traffic=''):
    return not candidate_reasons(row, overrides, auto_traffic)


def write_candidates(urls, path=CANDIDATES_TXT):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        for url in urls:
            f.write(url + '\n')


def load_candidates(path=CANDIDATES_TXT):
    if not os.path.isfile(path):
        raise FileNotFoundError(f'Candidates not found: {path}')
    urls = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                urls.append(line)
    return urls


def load_published(path=PUBLISHED_TXT):
    if not os.path.isfile(path):
        return []
    return load_candidates(path)


def load_manifest(path=MANIFEST_CSV):
    if not os.path.isfile(path):
        raise FileNotFoundError(f'Manifest not found: {path}')
    rows = []
    with open(path, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows


def http_fetch(url, timeout=15):
    """GET url; return (status, body, headers) or raise."""
    req = Request(url, headers={'User-Agent': _USER_AGENT})
    resp = _HTTP_OPENER.open(req, timeout=timeout)
    body = resp.read().decode('utf-8', errors='replace')
    return resp.status, body, dict(resp.headers)


def normalize_url(url):
    return url.strip().rstrip('/').lower()


def render_template(text, data, *, raw_keys=frozenset(), escape=html.escape):
    """Replace {{key}} placeholders; escape values unless listed in raw_keys."""
    placeholders = set(TEMPLATE_PLACEHOLDER_RE.findall(text))
    unknown = placeholders - set(data.keys())
    if unknown:
        raise ValueError(f'Unknown template keys: {sorted(unknown)}')
    for key in sorted(placeholders, key=len, reverse=True):
        val = data.get(key, '')
        out = val if key in raw_keys else escape(val)
        text = text.replace('{{' + key + '}}', out)
    return text


def render_template_file(path, data, **kwargs):
    with open(path, encoding='utf-8') as f:
        text = f.read()
    return render_template(text, data, **kwargs)


def load_destination(path=DESTINATION_CSV):
    if not os.path.isfile(path):
        raise FileNotFoundError(f'Destination config not found: {path}')
    with open(path, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            url = (row.get('destination_url') or '').strip()
            if not url or url.startswith('#'):
                continue
            return {
                'destination_url': url,
                'utm_source': (row.get('utm_source') or 'seo').strip(),
                'utm_medium': (row.get('utm_medium') or 'trafficpage').strip(),
                'utm_campaign': (row.get('utm_campaign') or '{host}').strip(),
                'cta_text': (row.get('cta_text') or 'Claim Bonus').strip(),
                'offer_block': (row.get('offer_block') or '').strip(),
            }
    raise ValueError(f'No destination row in {path}')


def build_conversion_url(dest, source_url):
    """Tracking link: destination + UTM (campaign = source hostname by default)."""
    host = (urlparse(source_url).hostname or 'unknown').replace(':', '_')
    campaign = dest.get('utm_campaign', '{host}').replace('{host}', host)
    base = dest['destination_url'].rstrip('/')
    query = urlencode({
        'utm_source': dest.get('utm_source', 'seo'),
        'utm_medium': dest.get('utm_medium', 'trafficpage'),
        'utm_campaign': campaign,
    })
    return f'{base}/?{query}'


def is_authorized(path=AUTHORIZED_FLAG):
    if os.environ.get('TRIAL_AUTHORIZED', '').lower() in ('1', 'true', 'yes'):
        return True
    if not os.path.isfile(path):
        return False
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line.startswith('#') or not line:
                continue
            if '=' in line:
                key, val = line.split('=', 1)
                if key.strip().lower() == 'authorized':
                    return val.strip().lower() == 'yes'
            if line.lower() == 'yes':
                return True
    return False
