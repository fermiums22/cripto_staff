Review only adaptive_engine.py, adaptive_research.py, adaptive_live.py and
tests/test_adaptive.py. Focus on lookahead, funding/fee accounting, isolated
bankruptcy, gap/stop ordering, pyramid sizing, stale data, SQLite restart and
duplicate-entry safety. The bot uses public data and PAPER only; do not read
secrets, invoke private APIs, change services or tune on the frozen holdout.
Return at most five concrete bugs: severity, file:line, short fix. No style review.
This is a second review; existing unit/HTTP tests have already passed. Do not edit.
