"""Shared constants for NextRce."""

MAX_THREADS = 500

REPORT_COLUMNS = [
    'url', 'status', 'access', 'user', 'hostname', 'os', 'nodejs', 'docker',
    'webroot', 'domain_type', 'traffic_value', 'notes', 'indexable', 'server_country',
]

# Post-scan enrichment: column -> shell command (success targets only)
ENRICH_COMMANDS = {
    'user':     'whoami',
    'hostname': 'hostname',
    'os':       'cat /etc/os-release',
    'nodejs':   'node -v',
    'docker':   "docker ps --format '{{.Names}}'",
    'webroot':  'pwd',
    'notes':    (
        'timeout 12 find /var/www /app /home /opt -maxdepth 8 -name package.json '
        '-not -path "*/node_modules/*" -not -path "*/.cache/*" '
        '-not -path "*/yarn/*" 2>/dev/null | head -5'
    ),
    'server_country': (
        "curl -fsS --max-time 8 https://ipinfo.io/country 2>/dev/null | tr -d '\\n' "
        "|| wget -qO- --timeout=8 https://ipinfo.io/country 2>/dev/null | tr -d '\\n'"
    ),
}

ENRICH_TIMEOUT = 30
FIND_HTTP_TIMEOUT = 25

# Stack / feature buckets written under results/ after each batch scan
STACK_DOMAIN_FILES = {
    'Next.js':   'nextjs.txt',
    'React':     'react.txt',
    'Laravel':   'laravel.txt',
    'WordPress': 'wordpress.txt',
    'Static':    'static.txt',
}
STACK_FEATURE_FILES = {
    'nodejs': 'nodejs.txt',
    'docker': 'docker.txt',
}
INDEXABLE_FILE = 'indexable.txt'
STACK_OUTPUT_FILES = (
    list(STACK_DOMAIN_FILES.values())
    + list(STACK_FEATURE_FILES.values())
    + [INDEXABLE_FILE]
)


class Colors:
    GREEN  = '\033[92m'
    RED    = '\033[91m'
    YELLOW = '\033[93m'
    BLUE   = '\033[94m'
    CYAN   = '\033[96m'
    GREY   = '\033[90m'
    BOLD   = '\033[1m'
    RESET  = '\033[0m'
