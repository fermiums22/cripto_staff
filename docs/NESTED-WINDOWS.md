# Nested windows and position scaling

Historical experiment requested 2026-10-29. SOLUSDT perpetual, seven cached days,
$10 initial capital, leverage10, max four virtual windows. First window requests
$2 margin before lot rounding. Further window budgets are $2 times 1/1.5/2 raised
to the current number of open windows. Insufficient free margin blocks an entry;
no borrowing of nonexistent capital or unlimited doubling is allowed.

Twelve configurations: same-side addition versus opposite-side addition, adverse
move .3%/.6% from the latest open window's entry, size multiplier 1/1.5/2.
Minimum five minutes between entries; additions require a losing basket.
SL10% price per window; basket target covers all accumulated net losses/expenses
plus .1% of active entry notional. Mark, funding, cost, margin and terminal close
assumptions are inherited from WINDOW-EXPERIMENT.md. No live orders enabled.

First five days and seeds0–4 select the best median among configurations with at
least ten median entries. Last two days use new seeds100–104; all candidates are
shown, but selection is not changed after seeing them. Stress widens costs and
can change the subsequent trade sequence. Previously examined history is not a
pristine holdout. Five random paths are not five independent market periods.

Selected: same-side, .6% adverse trigger, multiplier2. Selection median -5.59%,
evaluation median +3.32% (four of five positive), worst evaluation -2.35%, stress
median +.55%. Continuous full-week rerun median -2.87%, worst -15.07%, worst
drawdown24.09%. Positive two-day behavior did not establish nondeclining capital.

Run `python nested_windows.py`; report artifacts/nested_windows.json, dashboard
table and selected evaluation curves. Original window experiment defaults and
reports are preserved. Increasing stake scales nominal fees as well as exposure;
it is not a fee discount or evidence that losses will be recovered.
