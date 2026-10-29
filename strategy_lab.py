"""Fixed-hypothesis research, with separate validation and untouched final period."""
import json
import logging
import time

import agent

NAMES = {'xgboost': 'XGBoost: цена и объём', 'cross_asset': 'XGBoost + BTC/ETH',
         'momentum': 'Начало импульса', 'reversal': 'Откат после падения',
         'lead_lag': 'Запаздывание за BTC/ETH'}


def aligned_market(db):
    raw = {s: agent.read_bars(db, s) for s in agent.SYMBOLS}
    common = sorted(set.intersection(*[set(b[0] for b in bars) for bars in raw.values()]))
    if len(common) < 2000 or any(b-a != agent.BAR_MS for a, b in zip(common, common[1:])):
        raise ValueError('Aligned history must have at least 2000 contiguous candles')
    timestamps = set(common)
    return {s: [b for b in bars if b[0] in timestamps] for s, bars in raw.items()}


def cross_features(market, symbol, i):
    own = agent.features(market[symbol], i)
    btc = agent.features(market['BTCUSDT'], i)
    eth = agent.features(market['ETHUSDT'], i)
    if any(x is None for x in (own, btc, eth)):
        return None
    return own + btc[:6] + eth[:6] + [own[1]-btc[1], own[1]-eth[1]]


def rule_signals(market, symbol, i):
    x = agent.features(market[symbol], i)
    b = agent.features(market['BTCUSDT'], i)
    e = agent.features(market['ETHUSDT'], i)
    if any(v is None for v in (x, b, e)):
        return dict.fromkeys(('momentum', 'reversal', 'lead_lag'), 0)
    # Fixed before looking at evaluation outcomes; these are hypotheses, not facts.
    return {'momentum': int(x[1] > 0.003 and x[0] > 0 and x[7] > 0.5 and x[2] < 0.02),
            'reversal': int(x[2] < -0.008 and x[0] > 0 and x[7] > 0),
            'lead_lag': int(symbol not in ('BTCUSDT', 'ETHUSDT') and
                            max(b[1], e[1]) > 0.003 and -0.004 < x[1] < 0.001)}


def research(db):
    market = aligned_market(db)
    n = len(market['BTCUSDT'])
    validation, test = int(n*0.6), int(n*0.8)
    results = {name: {'name': title, 'symbols': {}} for name, title in NAMES.items()}
    training_indices = [i for i in range(24, validation) if i+agent.HORIZON < validation]
    for symbol, bars in market.items():
        targets = [int(bars[i+agent.HORIZON][4]*(1-agent.SLIP)*(1-agent.FEE) /
                       (bars[i+1][1]*(1+agent.SLIP)*(1+agent.FEE)) > 1) for i in training_indices]
        predictions = {}
        for name, feature in [('xgboost', lambda i: agent.features(bars, i)),
                              ('cross_asset', lambda i: cross_features(market, symbol, i))]:
            model = agent.fit_model([feature(i) for i in training_indices], targets)
            indices = list(range(validation, n-1))
            predictions[name] = dict(zip(indices, agent.probabilities(model, [feature(i) for i in indices])))
        for name in ('momentum', 'reversal', 'lead_lag'):
            predictions[name] = {i: rule_signals(market, symbol, i)[name] for i in range(validation, n-1)}
        for name, preds in predictions.items():
            val = agent.backtest(bars, preds, validation+1, test)
            outcome = agent.backtest(bars, {i: p for i, p in preds.items() if i >= test}, test+1, n, trace=True)
            # No interpolation of simulated PnL into a live account.
            baseline = (bars[-1][4]*(1-agent.SLIP)*(1-agent.FEE) /
                        (bars[test+1][1]*(1+agent.SLIP)*(1+agent.FEE))-1)*100
            outcome['buy_hold_pct'] = baseline
            outcome['curve'] = outcome['curve'][::6] + outcome['curve'][-1:]
            results[name]['symbols'][symbol] = {'validation': val, 'test': outcome}
    for result in results.values():
        values = list(result['symbols'].values())
        result['validation_mean_pct'] = sum(v['validation']['return_pct'] for v in values)/len(values)
        result['test_mean_pct'] = sum(v['test']['return_pct'] for v in values)/len(values)
        result['test_trades'] = sum(v['test']['trades'] for v in values)
    selected = max(results, key=lambda name: results[name]['validation_mean_pct'])
    candidate = results[selected]
    candidate['passes_initial_screen'] = candidate['test_mean_pct'] > 0 and candidate['test_trades'] >= 20
    report = {'created_ms': int(time.time()*1000), 'candles_per_symbol': n,
              'train_end_ms': market['BTCUSDT'][validation-1][0],
              'validation_start_ms': market['BTCUSDT'][validation][0],
              'test_start_ms': market['BTCUSDT'][test][0], 'test_end_ms': market['BTCUSDT'][-1][0],
              'selected_on_validation': selected, 'strategies': results,
              'auto_promoted': False, 'training_device': 'cuda:0',
              'notes': ['Кандидат выбран на validation, test не использован для настройки.',
                        'Результаты — историческая симуляция, отдельные $15 на каждый символ.',
                        'Нет исторического стакана и лимитов ордера. Издержки: комиссия 0.1% и проскальзывание 0.05% на сторону.',
                        'Положительный результат одного периода не доказывает доходность. Автозамена модели выключена.']}
    agent.ARTIFACTS.mkdir(exist_ok=True)
    target = agent.ARTIFACTS/'comparison.json'
    tmp = target.with_suffix('.tmp')
    tmp.write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
    tmp.replace(target)
    print(json.dumps({k: {x: v[x] for x in ('validation_mean_pct', 'test_mean_pct', 'test_trades')}
                      for k, v in results.items()}, ensure_ascii=False))
    return report


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    with agent.connect() as db:
        research(db)
