"""Independent long-entry adaptations of published Hummingbot controllers.

See docs/OPEN-SOURCE-STRATEGIES.md for sources and execution differences.
"""
import math
import statistics

NAMES={'hb_bollinger':'Hummingbot BB · адаптация', 'hb_macdbb':'Hummingbot MACD+BB · адаптация'}


def entry_scores(closes):
    out={k:[0.]*len(closes) for k in NAMES}
    fast=slow=macd_signal=None
    for i,close in enumerate(closes):
        fast=close if fast is None else fast+2/22*(close-fast)
        slow=close if slow is None else slow+2/43*(close-slow)
        macd=fast-slow
        macd_signal=macd if macd_signal is None else macd_signal+2/10*(macd-macd_signal)
        if i<199:continue  # Warm-up exceeds BB100 and MACD42 requirements.
        window=closes[i-99:i+1];mean=statistics.fmean(window)
        std=math.sqrt(sum((x-mean)**2 for x in window)/100)
        if std<=0:continue
        lower=mean-2*std
        if close<lower:
            score=(lower-close)/close
            out['hb_bollinger'][i]=score
            if macd<0 and macd-macd_signal>0:out['hb_macdbb'][i]=score
    return out


def aggregate(bars):
    """Only complete UTC-aligned 3-minute candles; no partial resampling."""
    grouped={}
    for b in bars:grouped.setdefault(b[0]//180000*180000,[]).append(b)
    result=[]
    for ts,rows in sorted(grouped.items()):
        rows=sorted(rows)
        if [r[0] for r in rows]!=[ts,ts+60000,ts+120000]:continue
        result.append([ts,rows[0][1],max(r[2] for r in rows),min(r[3] for r in rows),rows[-1][4],sum(r[5] for r in rows)])
    return result
