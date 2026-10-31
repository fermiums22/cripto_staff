"""Frozen experimental controls, NOT trained estimates or approved strategies."""
from brain_impulse_data import FEATURES


def signals(row,kind):
    if kind=='cash':return []
    x=dict(zip(FEATURES,row['x']))
    if row['symbol'] in ('BTCUSDT','ETHUSDT'):return []
    if kind=='momentum':
        move=x['return_30s']
    elif kind=='leadlag_flow':
        leader=(x['btc_30s']+x['eth_30s'])/2
        if abs(x['flow_5s'])<.6 or leader*x['flow_5s']<=0:return []
        if x['volatility_acceleration']<=0:return []
        move=leader-x['return_30s']
        if move*leader<=0:return []
    else:raise ValueError('Unknown control')
    # Historical move is only a fixed heuristic forecast; independent evidence
    # must establish whether it predicts anything. No confidence/profit claim.
    estimate=abs(move)-x['spread']-2*(.0006+.0003)
    return [dict(symbol=row['symbol'],observed_ms=row['ts'],session=row['session'],
        expected_net_return=estimate,uncertainty=0.,side=1 if move>0 else -1,horizon_ms=30000)]
