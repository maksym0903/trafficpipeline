"""HTTP helpers and SSL context for NextRce."""
import json
import os
import random
import re
import ssl
import string
from urllib.request import Request, ProxyHandler, HTTPSHandler, build_opener
from urllib.error import HTTPError

from nextrce_config import Colors


def ssl_verify_enabled():
    return os.environ.get('TRIAL_SSL_VERIFY', '0').lower() in ('1', 'true', 'yes')


def make_ssl_context():
    ctx = ssl.create_default_context()
    if not ssl_verify_enabled():
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


SSL_CTX = make_ssl_context()

def extract_url(line):
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    clean = ansi_escape.sub('', line)
    m = re.search(r'(https?://[a-zA-Z0-9.\-]+(?::\d+)?(?:/[^\s]*)?)', clean)
    return m.group(1).strip() if m else None


def sanitize_output(text):
    """
    过滤会导致终端崩溃的字符：
    - C0 控制符（除 \\n \\t 外）
    - U+0080-U+009F：C1 控制字符
    - U+00C0-U+00DF：UTF-8 编码后第二字节落在 0x80-0x9F（C1 区），
      部分终端将 \\x9F(APC) \\x93(STS) 等解读为控制指令导致 tty 关闭
    - DEL (0x7F)
    中文及 U+00E0 以上字符的 UTF-8 续字节均 >= 0xA0，安全，不转义。
    """
    result = []
    for ch in text:
        cp = ord(ch)
        if ch in ('\n', '\t'):
            result.append(ch)
        elif cp < 0x20 or cp == 0x7F:
            result.append(f'\\x{cp:02x}')
        elif 0x80 <= cp <= 0x9F:
            result.append(f'\\x{cp:02x}')
        elif 0xC0 <= cp <= 0xDF:
            # UTF-8: \xc3\x80-\xc3\x9F → 续字节在 C1 区，危险
            result.append(f'\\x{cp:02x}')
        else:
            result.append(ch)
    return ''.join(result)


def random_boundary():
    suffix = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
    return f"----FormBoundary{suffix}"


def escape_cmd(cmd):
    return cmd.replace("'", "'\\''")


def make_opener(proxy=None):
    handlers = [HTTPSHandler(context=SSL_CTX)]
    if proxy:
        handlers.append(ProxyHandler({"http": proxy, "https": proxy}))
    else:
        handlers.append(ProxyHandler({}))
    return build_opener(*handlers)


BASE_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def http_get(opener, url, timeout):
    req = Request(url, headers=BASE_HEADERS)
    try:
        resp = opener.open(req, timeout=timeout)
        body = resp.read().decode('utf-8', errors='replace')
        return resp.headers, body, resp.status
    except HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        return e.headers, body, e.code
    except Exception:
        raise


def http_post(opener, url, data, extra_headers, timeout):
    if isinstance(data, str):
        data = data.encode('utf-8')
    headers = {**BASE_HEADERS, **extra_headers}
    req = Request(url, data=data, headers=headers, method='POST')
    try:
        resp = opener.open(req, timeout=timeout)
        body = resp.read().decode('utf-8', errors='replace')
        return body, resp.status
    except HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        return body, e.code
    except Exception:
        raise
