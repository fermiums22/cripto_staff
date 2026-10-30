#!/bin/sh
cd /home/codex/workspace/cripto_staff || exit 1
export LD_LIBRARY_PATH=/opt/nvidia-driver
export PYTHONPATH=/home/codex/workspace/cripto_staff/.gpu-torch:/home/codex/workspace/cripto_staff/.venv/lib/python3.13/site-packages:/home/codex/projects/market-brain-storage/cuda-packages
exec .venv/bin/python -u brain_supervisor.py
