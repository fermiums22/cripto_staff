"""Restartable, finite evidence workflow. Never touches existing PAPER/Telegram units."""
import fcntl, json, os, pathlib, subprocess, sys, time
from brain_research import ROOT, STORE, write
RUN=STORE/"run-20261030-c"
CHANNELS=STORE/"channels"
def main():
    STORE.mkdir(parents=True,exist_ok=True)
    lock=(ROOT/"data/brain-supervisor.lock").open("a")
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:return
    os.nice(10)
    children={};last_micro=0
    saved=STORE/"supervisor.json"
    if saved.exists():last_micro=json.loads(saved.read_text()).get("last_micro",0)
    while True:
        tasks={"channels":["brain_channels.py","--directory",str(CHANNELS)]}
        if (RUN/"frozen.json").exists() and not (RUN/"prospective_result.json").exists():
            tasks["forward"]=["brain_forward.py","--run",str(RUN)]
        now=time.time()
        if now-last_micro>=86400:
            tasks["micro"]=["brain_microstructure.py","--directory",str(CHANNELS)]
        for name,args in tasks.items():
            if name in children and children[name].poll() is None:continue
            log=(STORE/(name+".log")).open("a")
            children[name]=subprocess.Popen([sys.executable,"-u",*args],cwd=ROOT,stdout=log,stderr=log)
            log.close()
            if name=="micro":last_micro=now
        status=dict(updated_ms=int(now*1000),last_micro=last_micro,run=str(RUN),ready=False,
                    children={k:dict(pid=p.pid,exit_code=p.poll()) for k,p in children.items()},
                    mode="research PAPER only; rejected candidate stays cash; no automatic promotion")
        write(saved,status)
        time.sleep(30)
if __name__=="__main__":main()
