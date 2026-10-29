"""Read-only Bybit execution/cost audit. Never sends orders or changes positions."""
import hashlib
import argparse
import hmac
import json
import os
import time
import urllib.parse
import urllib.request
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CREDENTIAL_PATH = ROOT/'secrets/bybit.key'
ALLOWED = {'/v5/account/fee-rate', '/v5/order/realtime', '/v5/order/history',
           '/v5/execution/list', '/v5/position/list', '/v5/account/transaction-log',
           '/v5/market/tickers', '/v5/market/instruments-info'}


def request(path, params):
    if path not in ALLOWED:
        raise ValueError('Read-only endpoint not allowed')
    query = urllib.parse.urlencode(params)
    headers = {}
    if not path.startswith('/v5/market/'):
        lines = CREDENTIAL_PATH.read_text(encoding='utf-8-sig').splitlines()
        if len(lines) != 3:
            raise ValueError('Invalid credential file')
        _, key, secret = [v.strip() for v in lines]
        ts = str(int(time.time()*1000))
        sig = hmac.new(secret.encode(), (ts+key+'5000'+query).encode(), hashlib.sha256).hexdigest()
        headers = {'X-BAPI-API-KEY': key, 'X-BAPI-TIMESTAMP': ts,
                   'X-BAPI-RECV-WINDOW': '5000', 'X-BAPI-SIGN': sig}
    req = urllib.request.Request('https://api.bybit.com'+path+'?'+query, headers=headers, method='GET')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=20) as response:
        data = json.load(response)
    if data.get('retCode') != 0:
        # Raw errors may contain signing material.
        raise RuntimeError('Bybit code '+str(data.get('retCode')))
    return data['result']


def pages(path, params):
    rows = []; seen = set()
    while True:
        data = request(path, params)
        rows.extend(data.get('list', []))
        cursor = data.get('nextPageCursor')
        if not cursor:
            return rows
        if cursor in seen:
            raise RuntimeError('Repeated pagination cursor')
        seen.add(cursor)
        params = dict(params, cursor=cursor)


def audit(symbol='AAVEPERP'):
    end = int(time.time()*1000); start = end-24*3600*1000
    base = dict(category='linear', symbol=symbol)
    history = dict(base, startTime=start, endTime=end, limit=100)
    jobs = {
        'fee_rates': ('/v5/account/fee-rate', base),
        'open_orders': ('/v5/order/realtime', dict(base, openOnly=0, limit=50)),
        'order_history': ('/v5/order/history', dict(history, limit=50)),
        'executions': ('/v5/execution/list', history),
        'positions': ('/v5/position/list', base),
        'transactions': ('/v5/account/transaction-log', dict(accountType='UNIFIED',
            category='linear', currency='USDC', startTime=start, endTime=end, limit=50)),
        'ticker': ('/v5/market/tickers', base),
        'instrument': ('/v5/market/instruments-info', base),
    }
    report = dict(symbol=symbol, start_ms=start, end_ms=end, errors={}, read_only=True)
    for name, (path, params) in jobs.items():
        try:
            report[name] = pages(path, params)
            if name == 'transactions':
                # Preserve unallocated interest separately; never assign it to this trade.
                report['unallocated_interest'] = [r for r in report[name]
                    if r.get('type') == 'INTEREST' and r.get('symbol') != symbol]
                report[name] = [r for r in report[name] if r.get('symbol') == symbol]
        except Exception as exc:
            report['errors'][name] = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
    directory = ROOT/'artifacts/fee-audits'
    directory.mkdir(parents=True, exist_ok=True)
    path = directory/f'{symbol}-{end}.json'
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2)
    summary = dict(saved=str(path), errors=report['errors'])
    for name, fields in {
        'fee_rates': ('symbol','makerFeeRate','takerFeeRate'),
        'open_orders': ('symbol','side','orderStatus','price','qty','cumExecQty','cumExecFee'),
        'positions': ('symbol','side','size','avgPrice','leverage','unrealisedPnl'),
        'executions': ('symbol','execType','side','execPrice','execQty','execFee','feeCurrency','feeRate','isMaker','execTime'),
        'transactions': ('type','currency','fee','funding','cashFlow','change','transactionTime'),
        'ticker': ('bid1Price','ask1Price','markPrice','fundingRate','nextFundingTime','fundingIntervalHour'),
        'instrument': ('symbol','settleCoin','fundingInterval'),
    }.items():
        summary[name] = [{k: r.get(k) for k in fields} for r in report.get(name, [])]
    summary['unallocated_interest_records'] = len(report.get('unallocated_interest', []))
    # Funding/execution records can describe the same debit: do not sum both sources.
    if 'transactions' in report:
        totals = {}
        for row in report['transactions']:
            total = totals.setdefault(row['currency'], dict(fee=Decimal(0), funding=Decimal(0)))
            for k in total:
                total[k] += Decimal(row.get(k) or '0')
        summary['ledger_totals'] = {c: {k: str(v) for k,v in t.items()} for c,t in totals.items()}
    print(json.dumps(summary))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--symbol', default='AAVEPERP', help='API symbol, not display name')
    parser.add_argument('--credentials', type=Path, default=CREDENTIAL_PATH)
    args = parser.parse_args()
    CREDENTIAL_PATH = args.credentials
    audit(args.symbol)
