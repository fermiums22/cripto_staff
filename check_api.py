"""Verify a three-line Bybit credential file without printing credentials."""
import hashlib
import hmac
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def check(path):
    lines = path.read_text(encoding='utf-8-sig').splitlines()
    if len(lines) != 3 or not all(line.strip() for line in lines):
        raise ValueError('Expected name, API key, secret on three separate lines')
    _, key, secret = [line.strip() for line in lines]
    timestamp = str(int(time.time()*1000))
    window = '5000'
    signature = hmac.new(secret.encode(), (timestamp+key+window).encode(), hashlib.sha256).hexdigest()
    request = urllib.request.Request('https://api.bybit.com/v5/user/query-api', headers={
        'X-BAPI-API-KEY': key, 'X-BAPI-TIMESTAMP': timestamp,
        'X-BAPI-RECV-WINDOW': window, 'X-BAPI-SIGN': signature,
    })
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=20) as response:
        result = json.load(response)
    # retMsg can contain signing inputs on errors: never print raw API responses.
    if result.get('retCode') != 0:
        print(json.dumps({'ok': False, 'code': result.get('retCode')}))
        return 1
    info = result['result']
    readonly = str(info.get('readOnly')) == '1'
    bound = bool(info.get('ips')) and not any(ip in ('*', '0.0.0.0') for ip in info['ips'])
    print(json.dumps({'ok': True, 'read_only': readonly, 'ip_bound': bound,
                      'real_trading_enabled': False}))
    return 0


if __name__ == '__main__':
    try:
        credential_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent/'secrets/bybit.key'
        sys.exit(check(credential_path))
    except Exception as exc:
        print(json.dumps({'ok': False, 'error_type': type(exc).__name__}))
        sys.exit(1)
