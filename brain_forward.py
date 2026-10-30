"""Frozen prospective research PAPER. Public GET only, separate wallets, no promotion."""
import argparse, fcntl, json, math, os, pathlib, time
from decimal import Decimal, ROUND_DOWN
import numpy as np
from brain_research import ROOT, SYMBOLS, STEP, FEE, SLIP, digest, write, predict
from motivation_core import Opportunity, assess
from agent import api

ALLOWED = frozenset(["kline","tickers","orderbook","instruments-info","funding/history"])
def now_ms():return int(time.time()*1000)

def public(endpoint, **params):
    if endpoint not in ALLOWED:raise ValueError("public endpoint not allowed")
    start=now_ms(); result=api(endpoint,category="linear",**params);received=now_ms()
    if received-start>1500:raise ValueError("request latency exceeds budget")
    stamp=int(result["time"])
    if abs(received-stamp)>1500:raise ValueError("clock drift or stale server")
    return result,start,received

def paused():
    import sqlite3
    try:
        with sqlite3.connect("file:"+str(ROOT/"data/agent.sqlite3")+"?mode=ro",uri=True) as db:
            row=db.execute("SELECT value FROM state WHERE key='control'").fetchone()
        return bool(row and json.loads(row[0]).get("paused",False))
    except Exception:return True

def book(symbol):
    response,start,received=public("orderbook",symbol=symbol,limit=50)
    b=response["result"]
    if not 0<=received-int(b["ts"])<=1500:raise ValueError("stale orderbook")
    bids=[list(map(float,r)) for r in b["b"]];asks=[list(map(float,r)) for r in b["a"]]
    if not bids or not asks or bids[0][0]>=asks[0][0]:raise ValueError("crossed or empty book")
    if any(not math.isfinite(p*q) or p<=0 or q<=0 for p,q in bids+asks):raise ValueError("bad depth")
    return dict(bids=bids,asks=asks,event_ms=int(b["ts"]),received_ms=received,
                request_ms=start,rtt_ms=received-start,seq=b.get("seq"),update_id=b.get("u"))

def fill(levels,qty):
    left=qty;value=0.
    for price,available in levels:
        take=min(left,available);value+=take*price;left-=take
        if left<=1e-10:break
    if left>1e-10:raise ValueError("insufficient visible depth")
    return value/qty

def quantity(notional,price,instrument):
    lot=instrument["lotSizeFilter"];step=Decimal(lot["qtyStep"])
    qty=float((Decimal(str(notional/price))/step).to_integral_value(rounding=ROUND_DOWN)*step)
    if qty<float(lot["minOrderQty"]) or qty*price<float(lot.get("minNotionalValue","0")):
        raise ValueError("order minimum exceeds risk budget")
    if qty>float(lot.get("maxMktOrderQty",lot["maxOrderQty"])):raise ValueError("order maximum")
    return qty

def funding_cost(position, exit_ms):
    response,_,_=public("funding/history",symbol=position["symbol"],
          startTime=position["opened_ms"]+1,endTime=exit_ms,limit=200)
    rows=response["result"]["list"]
    if len(rows)>=200:raise ValueError("funding history pagination required")
    total=0.
    for r in rows:
        t=int(r["fundingRateTimestamp"])
        if position["opened_ms"]<t<=exit_ms:
            # Funding notional uses event mark, unavailable here. Conservative upper
            # bound based on max observed mark/entry/exit, credits ignored.
            rate=float(r["fundingRate"])*position["side"]
            total+=max(rate,0)*position["qty"]*position["max_mark"]
    return total

def initial(protocol):
    return dict(version=1,protocol_sha256=digest(protocol),last_slot=0,cycles=0,errors=[],
       wallets={k:dict(cash=15.,peak=15.,equity=15.,max_drawdown=0.,position=None,
                      pending=None,trades=[],decisions={},halted=False)
                for k in ["candidate","momentum","reversal","cash"]},
       channels={},started_ms=now_ms(),observations=0)

def record_decision(w,reason):
    w["decisions"][reason]=w["decisions"].get(reason,0)+1

def close_position(w,b,reason):
    p=w["position"]
    price=fill(b["bids"] if p["side"]>0 else b["asks"],p["qty"])
    price*=1-SLIP if p["side"]>0 else 1+SLIP
    p["max_mark"]=max(p["max_mark"],price)
    funding=funding_cost(p,b["received_ms"])
    fee=p["qty"]*price*FEE
    gross=p["side"]*p["qty"]*(price-p["entry"])
    w["cash"]+=gross-fee-funding
    w["trades"].append(dict(**p,exit=price,closed_ms=b["received_ms"],exit_reason=reason,
             exit_fee=fee,funding=funding,net_pnl=gross-fee-funding-p["entry_fee"],
             exit_rtt_ms=b["rtt_ms"]))
    w["position"]=None;w["equity"]=w["cash"]

def mark(w,quote):
    p=w["position"]
    if not p:return
    mark=float(quote["markPrice"]);p["max_mark"]=max(p["max_mark"],mark)
    liquidation_side=float(quote["bid1Price"] if p["side"]>0 else quote["ask1Price"])
    w["equity"]=w["cash"]+p["side"]*p["qty"]*(liquidation_side-p["entry"])-p["qty"]*liquidation_side*(FEE+SLIP)
    w["peak"]=max(w["peak"],w["equity"])
    w["max_drawdown"]=max(w["max_drawdown"],1-w["equity"]/w["peak"])
    if w["max_drawdown"]>=.10:w["halted"]=True

def verify(run):
    protocol=json.loads((run/"protocol.json").read_text())
    frozen=json.loads((run/"frozen.json").read_text())
    if digest(run/"protocol.json")!=frozen["protocol_sha256"]:raise ValueError("protocol changed")
    for path,sha in protocol["artifact_hashes"].items():
        if digest(run/path)!=sha:raise ValueError("model changed")
    for path,sha in protocol["source_code_sha256"].items():
        if digest(ROOT/path)!=sha:raise ValueError("frozen code changed")
    return protocol

def candles():
    data={}; stamps=[]
    for s in SYMBOLS:
        response,_,received=public("kline",symbol=s,interval="15",limit=40)
        rows={int(r[0]):list(map(float,r[:6])) for r in response["result"]["list"]
              if int(r[0])+STEP<=int(response["time"])}
        data[s]=rows;stamps.append(received)
    ts=sorted(set.intersection(*(set(v) for v in data.values())))[-32:]
    if len(ts)!=32 or any(b-a!=STEP for a,b in zip(ts,ts[1:])):
        raise ValueError("candle history gap")
    if not 0<=now_ms()-ts[-1]-STEP<=60000:raise ValueError("missed timely signal window")
    return np.array([[data[s][t] for s in SYMBOLS] for t in ts]),ts[-1]+STEP,max(stamps)

def evaluate(state,protocol):
    days=14;start=protocol["future_start_ms"]
    arrays={};details={}
    for name,w in state["wallets"].items():
        daily=np.zeros(days)
        for tr in w["trades"]:
            day=min(days-1,max(0,(tr["closed_ms"]-start)//86400000))
            daily[day]+=tr["net_pnl"]/15.
        arrays[name]=daily
        details[name]=dict(closed_trades=len(w["trades"]),net_pnl=w["cash"]-15.,
             max_drawdown=w["max_drawdown"],symbols=len(set(t["symbol"] for t in w["trades"])),
             has_open_position=w["position"] is not None)
    rng=np.random.default_rng(812);ids=rng.integers(0,days,(10000,days))
    lower={k:float(np.quantile((arrays["candidate"]-v)[ids].mean(axis=1),.0125))
           for k,v in arrays.items() if k!="candidate"}
    c=details["candidate"]
    coverage=state["observations"]/(14*96)
    statistical_pass=(coverage>=.95 and c["closed_trades"]>=100 and c["symbols"]>=3 and
        c["max_drawdown"]<=.10 and all(x>0 for x in lower.values()) and
        not any(w["position"] or w["pending"] for w in state["wallets"].values()))
    return dict(protocol_sha256=state["protocol_sha256"],finished_ms=now_ms(),wallets=details,
        paired_daily_lower_bounds=lower,signal_coverage=coverage,statistical_pass=statistical_pass,ready=False,
        reasons=["Costs remain conservative scenarios; event funding marks and independent execution audit required.",
                 "15m model does not establish subsecond impulse entry capability."],
        next_action="Reject candidate" if not statistical_pass else "Independent cost and execution review")

def run_worker(run,once=False):
    lock=(ROOT/"data"/"brain-forward.lock").open("a")
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    protocol=verify(run);statepath=run/"forward_state.json"
    state=json.loads(statepath.read_text()) if statepath.exists() else initial(run/"protocol.json")
    if state["protocol_sha256"]!=digest(run/"protocol.json"):raise ValueError("state belongs to different experiment")
    instruments={};last_inst=0;last_checkpoint=0
    while True:
        try:
            verify(run)
            now=now_ms()
            if now-last_inst>3600000:
                fresh={}
                for s in SYMBOLS:
                    r,_,_=public("instruments-info",symbol=s)
                    inst=r["result"]["list"][0]
                    if inst["status"]!="Trading":raise ValueError("instrument not trading")
                    fresh[s]=inst
                instruments=fresh;last_inst=now
            response,started,received=public("tickers")
            quotes={r["symbol"]:r for r in response["result"]["list"] if r["symbol"] in SYMBOLS}
            if len(quotes)!=len(SYMBOLS):raise ValueError("missing ticker")
            state["channels"]={s:{k:q.get(k) for k in ["bid1Price","ask1Price","markPrice",
                "indexPrice","fundingRate","nextFundingTime","openInterest","volume24h"]} for s,q in quotes.items()}
            state["channels_received_ms"]=received;state["ticker_rtt_ms"]=received-started
            is_paused=paused()
            for label,w in state["wallets"].items():
                p=w["position"]
                if p:
                    mark(w,quotes[p["symbol"]])
                    price=float(quotes[p["symbol"]]["bid1Price"] if p["side"]>0 else quotes[p["symbol"]]["ask1Price"])
                    stop=p["side"]*(price/p["entry"]-1)<=-.01
                    end=received>=protocol["future_end_ms"]
                    if received>=p["exit_due_ms"] or stop or w["halted"] or end:
                        # Exit after a new book request, never at the triggering stale quote.
                        close_position(w,book(p["symbol"]),"stop" if stop else "risk" if w["halted"] else "time")
                pending=w["pending"]
                if pending and now_ms()>=pending["eligible_ms"]:
                    w["pending"]=None
                    if is_paused or w["halted"] or received>=protocol["future_end_ms"]:
                        record_decision(w,"paused_or_halted")
                        continue
                    if now_ms()-pending["decision_ms"]>15000:
                        record_decision(w,"expired_intent");continue
                    b=book(pending["symbol"]);side=pending["side"]
                    ask=b["asks"][0][0];bid=b["bids"][0][0];mid=(ask+bid)/2
                    spread=(ask-bid)/mid;levels=b["asks"] if side>0 else b["bids"]
                    notional=min(12.,w["cash"]*.8)
                    depth=sum(p*q for p,q in levels if abs(p/mid-1)<=.002)
                    o=Opportunity(symbol=pending["symbol"],observed_ms=b["event_ms"],now_ms=now_ms(),
                        expected_move=abs(pending["prediction"]),confidence=.5,roundtrip_fee=2*FEE,
                        spread=spread,slippage=2*SLIP,funding=abs(float(quotes[pending["symbol"]]["fundingRate"])),
                        liquidation_risk=0.,depth_usd=depth,required_notional_usd=notional,
                        uncertainty=.1,source_count=1)
                    decision=assess(o)
                    if not decision.eligible:record_decision(w,decision.reason);continue
                    qty=quantity(notional,ask if side>0 else bid,instruments[pending["symbol"]])
                    price=fill(levels,qty)*(1+SLIP if side>0 else 1-SLIP)
                    if qty*price>notional*1.01:record_decision(w,"execution_price_drift");continue
                    fee=qty*price*FEE;w["cash"]-=fee
                    w["position"]=dict(symbol=pending["symbol"],side=side,qty=qty,entry=price,
                         entry_fee=fee,opened_ms=b["received_ms"],exit_due_ms=pending["signal_ms"]+STEP,
                         decision_ms=pending["decision_ms"],signal_ms=pending["signal_ms"],
                         actual_delay_ms=b["received_ms"]-pending["decision_ms"],entry_rtt_ms=b["rtt_ms"],
                         prediction=pending["prediction"],max_mark=max(price,float(quotes[pending["symbol"]]["markPrice"])))
                    record_decision(w,"shadow_fill")
            now=now_ms()
            if now>=protocol["future_end_ms"]:
                if not any(w["position"] for w in state["wallets"].values()):
                    write(statepath,state);write(run/"prospective_result.json",evaluate(state,protocol));return
            elif now>=protocol["future_start_ms"] and now//STEP>state["last_slot"] and now%STEP<45000:
                a,signal_ms,observed=candles()
                predictions=predict(run,a,[c["name"] for c in protocol["frozen"]]+["ridge","mlp-17","mlp-53"])
                with (run/"prospective_forecasts.jsonl").open("a") as log:
                    log.write(json.dumps(dict(received_ms=observed,signal_ms=signal_ms,
                        forecasts={k:v.tolist() for k,v in predictions.items()},candles=a.tolist()))+"\n")
                decision_ms=now_ms()
                for config in protocol["frozen"]:
                    w=state["wallets"][config["label"]]
                    if w["position"] or w["pending"] or is_paused or w["halted"]:continue
                    values=predictions[config["name"]]
                    j=int(np.argmax(np.abs(values)));value=float(values[j])
                    if not math.isfinite(value) or abs(value)<=config["threshold"]:
                        record_decision(w,"no_edge");continue
                    w["pending"]=dict(symbol=SYMBOLS[j],side=1 if value>0 else -1,prediction=value,
                         decision_ms=decision_ms,eligible_ms=decision_ms+protocol["latency_ms"],signal_ms=signal_ms)
                state["last_slot"]=signal_ms//STEP;state["observations"]+=1
            state["cycles"]+=1;state["updated_ms"]=now_ms();state["paused"]=is_paused
            write(statepath,state)
            # Durable bounded channel observations. No credentials, no trade POST.
            if now-last_checkpoint>=60000:
                with (run/"channels.jsonl").open("a") as f:
                    f.write(json.dumps(dict(received_ms=received,event_ms=int(response["time"]),
                                           rtt_ms=received-started,channels=state["channels"]))+"\n")
                last_checkpoint=now
        except Exception as exc:
            state["errors"]=(state["errors"]+[dict(ms=now_ms(),type=type(exc).__name__,message=str(exc)[:180])])[-100:]
            state["updated_ms"]=now_ms()
            write(statepath,state)
            print(json.dumps(state["errors"][-1]),flush=True)
        if once:return
        time.sleep(5)

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--run",type=pathlib.Path,required=True);p.add_argument("--once",action="store_true")
    a=p.parse_args();run_worker(a.run,a.once)
