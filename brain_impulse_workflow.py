"""Restartable isolated research workflow; no trading or promotion endpoint."""
import argparse
import fcntl
import json
from pathlib import Path
import subprocess
import time
from brain_impulse_data import atomic_json


def run(campaign,output):
    output.mkdir(parents=True,exist_ok=True)
    with (output/'workflow.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        summary=campaign/'summary.json'
        if not summary.exists():
            atomic_json(output/'workflow-status.json',dict(stage='waiting_for_complete_campaign',ready=False));return
        if json.loads(summary.read_text()).get('coverage_admitted') is not True:
            atomic_json(output/'workflow-status.json',dict(stage='data_coverage_rejected',ready=False));return
        root=Path(__file__).resolve().parent
        for script in ('brain_impulse_train.py','brain_impulse_evaluate.py'):
            atomic_json(output/'workflow-status.json',dict(stage=script,updated_ms=time.time_ns()//1000000,ready=False))
            subprocess.run(['/bin/sh',str(root/'deploy/brain-supervisor.sh'),script,
                            '--campaign',str(campaign),'--output',str(output)],cwd=root,check=True)
        atomic_json(output/'workflow-status.json',dict(stage='validation_complete_no_promotion',
            updated_ms=time.time_ns()//1000000,ready=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--campaign',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();run(a.campaign,a.output)
