"""Event-depth historical development replay, never independent PAPER evidence.

Predictors receive only causal feature rows. Every account sees the same public
book stream. Receipt delays, fees and historical instrument rules are scenarios.
"""
from pathlib import Path
import json
from brain_archive_stream import ArchiveSource, merged, sha
from brain_impulse_data import ImpulseSampler
from brain_impulse_execution import ExecutionPolicy, initial_state, on_book, decide
from brain_impulse_protocol import trade_report


def archive_events(plan_path):
    plan=json.loads(Path(plan_path).read_text())
    if plan['mode']!='historical_development_only':
        raise ValueError('Historical source must remain development only')
    sources=[]
    for spec in plan['sources']:
        path=Path(spec['path'])
        if sha(path)!=spec['sha256']:raise ValueError('Archive hash changed')
        sources.append(ArchiveSource(path,spec['symbol'],spec['day'],spec['kind'],spec['delay_ms']))
    sampler=ImpulseSampler();last_book={}
    for raw in merged(sources):
        sample=sampler.ingest(raw);now=raw['received_ms'];message=raw['message']
        symbol=message['topic'].split('.')[-1];quote=None
        if message['topic'].startswith('orderbook.') and symbol in sampler.books:
            book=sampler.books[symbol]
            if book['received_ms']==now and now-last_book.get(symbol,0)>=200:
                last_book[symbol]=now
                quote=dict(ts=now,event_ms=int(message['ts']),symbol=symbol,session=raw['session'],
                    bids=sorted(book['b'].items(),reverse=True)[:50],asks=sorted(book['a'].items())[:50])
        # Every raw event advances the decision clock, as in the live runner.
        yield dict(ts=now,book=quote,sample=sample)
    if not all(source.stats['crc_complete'] for source in sources):
        raise ValueError('Incomplete raw replay')


def replay(events,predictors,instruments,start_ms,end_ms,policy=ExecutionPolicy()):
    if end_ms<=start_ms:raise ValueError('Empty replay interval')
    accounts={name:initial_state(policy) for name in predictors}
    cache={name:{} for name in predictors};due=None;next_decision=start_ms;previous=-1
    count=0;quotes=0;samples=0
    for event in events:
        now=event['ts']
        if now<previous:raise ValueError('Replay clock regression')
        previous=now
        if now<start_ms:continue
        if now>=end_ms:continue  # Exhaust source to validate CRC; never use later prices.
        count+=1;closing=now>=end_ms-180000
        quote=event.get('book');sample=event.get('sample')
        if quote:
            if quote['ts']!=now:raise ValueError('Book time differs from event')
            quotes+=1
            for state in accounts.values():on_book(state,quote,instruments,policy,paused=closing)
        if sample:
            if sample['ts']!=now:raise ValueError('Feature time differs from event')
            samples+=1
            for name,predictor in predictors.items():
                options=predictor(sample)
                for option in options:
                    if option['observed_ms']!=now or option['symbol']!=sample['symbol'] or option['session']!=sample['session']:
                        raise ValueError('Forecast identity does not match causal observation')
                cache[name][sample['symbol']]=options
            if now>=next_decision and due is None:due=now+500
        if due is not None and now>=due:
            for name,state in accounts.items():
                decide(state,[s for values in cache[name].values() for s in values],now,policy,paused=closing)
            next_decision=now+4500;due=None
        # Intent journal is operational data; avoid unbounded retention in replay.
        for state in accounts.values():state['events'].clear()
    reports={}
    for name,state in accounts.items():
        report=trade_report(state['trades'],start_ms,end_ms,policy.initial_cash)
        residual=state['cash']-policy.initial_cash-sum(t['net_pnl'] for t in state['trades'])
        if state['position']:residual+=state['position']['entry_fee']
        if abs(residual)>1e-8:raise ValueError('Replay accounting identity failed')
        issues=list(state['evidence_issues'])
        if state['position'] or state['pending']:issues.append('unresolved_end_state')
        report.update(mark_to_market_drawdown=state['max_drawdown'],final_cash=state['cash'],
            final_equity=state['equity'],accounting_residual=residual,evidence_issues=issues,
            execution_valid=not issues and count>0 and quotes>0,decisions=state['decisions'],
            reasons=state['reasons'],trades_detail=state['trades'],ready=False)
        reports[name]=report
    return dict(reports=reports,events=count,books=quotes,samples=samples,ready=False,
        independent_paper_evidence=False,mode='historical_development_event_depth_scenario')
