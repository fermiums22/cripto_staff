"""Research-only risk motivation and execution admissibility, no exchange orders.

Motivation influences ranking and exploration, never overrides entry constraints.
All inputs must be timestamped at observation time; no future features.
"""
from dataclasses import dataclass
from math import isfinite

@dataclass(frozen=True)
class Opportunity:
    symbol: str
    observed_ms: int
    now_ms: int
    expected_move: float
    confidence: float
    roundtrip_fee: float
    spread: float
    slippage: float
    funding: float
    liquidation_risk: float
    depth_usd: float
    required_notional_usd: float
    novelty: float = 0.0
    uncertainty: float = 0.0
    source_count: int = 1

@dataclass(frozen=True)
class Motives:
    opportunity_drive: float = .65
    curiosity: float = .20
    capital_survival: float = 1.0
    impatience: float = 0.0  # explicitly NOT a reason to trade

@dataclass(frozen=True)
class Decision:
    eligible: bool
    score: float
    net_edge: float
    reason: str

def assess(o: Opportunity, m: Motives = Motives(), max_age_ms: int=1500,
           max_liquidation_risk: float=.01, min_net_edge: float=.0008) -> Decision:
    values=(o.expected_move,o.confidence,o.roundtrip_fee,o.spread,o.slippage,o.funding,
            o.liquidation_risk,o.depth_usd,o.required_notional_usd,o.novelty,o.uncertainty)
    if not all(isfinite(v) for v in values):return Decision(False,0,0,'invalid_numeric_input')
    if o.observed_ms > o.now_ms or o.now_ms-o.observed_ms > max_age_ms:
        return Decision(False,0,0,'stale_or_future_signal')
    if not 0 <= o.confidence <= 1 or o.source_count < 1:
        return Decision(False,0,0,'unverified_signal')
    if any(x < 0 for x in (o.roundtrip_fee,o.spread,o.slippage,o.funding,o.liquidation_risk)):
        return Decision(False,0,0,'invalid_cost_or_risk')
    cost=o.roundtrip_fee+o.spread+o.slippage+o.funding
    edge=o.expected_move-cost
    if o.depth_usd < o.required_notional_usd * 5 or o.required_notional_usd <= 0:
        return Decision(False,0,edge,'insufficient_liquidity')
    if o.liquidation_risk > max_liquidation_risk:
        return Decision(False,0,edge,'liquidation_risk')
    if edge < min_net_edge:
        return Decision(False,0,edge,'insufficient_net_edge')
    # uncertainty subtracts from the score; novelty rewards research, not opening trades
    score=(m.opportunity_drive*edge*o.confidence -
           m.capital_survival*(o.uncertainty*abs(edge)+o.liquidation_risk))
    return Decision(score>0,score,edge,'qualified' if score>0 else 'low_risk_adjusted_score')
