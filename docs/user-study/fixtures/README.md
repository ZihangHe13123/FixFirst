# Fictional example data (DEMO)

**Made up to check `analysis.py`; not data from any participant.** The tables follow
[DATA.md](../DATA.md) and include the cases the rules must handle: the template's example row, a
pilot participant, a participant without a questionnaire (P05), and one who left after the first
round (P06: one task withdrawn, one never started, an incomplete SUS). `DEMO_RESULTS.md` is the
script's output for them:

```bash
.venv/bin/python docs/user-study/analysis.py --demo \
    --sessions docs/user-study/fixtures/demo_sessions.csv \
    --questionnaire docs/user-study/fixtures/demo_questionnaire.csv \
    --causes docs/user-study/fixtures/demo_cause_scores.csv \
    --output docs/user-study/fixtures/DEMO_RESULTS.md
```

`tests/test_user_study_analysis.py` checks every number below, worked out by hand.

| Measure | FixFirst | Baseline |
|---|---|---|
| Usable tasks | 12 (P01–P06, 2 each) | 10 (P01–P05; P06's T1 withdrawn, T2 absent) |
| Completed | 10 → 10/12 = 83.3% | 7 → 7/10 = 70.0% |
| Completed times, sorted | 100 150 200 210 250 280 300 320 350 400 | 400 450 500 550 600 610 650 |
| Median of completed tasks | (250 + 280) / 2 = 265 | 550 |
| Target | (550 − 265) / 550 = 51.8% lower | |
| Median, unfinished as 720 | the list above plus 720, 720 → (280 + 300) / 2 = 290 | plus 720, 720, 720 → (600 + 610) / 2 = 605 |
| False completion claims | 5 in 4 of 12 tasks | 8 in 5 of 10 tasks |
| Tests modified | 0 of 12 | 1 of 10 (P01 T4, not completed) |
| Confidence median | 12 values → 4 | 10 values → (3 + 4) / 2 = 3.5 |
| Cause scores | 8 correct, 2 partly, 1 wrong, 1 unscored → 8/11 = 72.7% | 4, 2, 3, 1 unscored → 4/9 = 44.4% |

Paired comparison (mean of two tasks; unfinished as 720; FixFirst − baseline):

| Participant | FixFirst | Baseline | Difference |
|---|---|---|---|
| P01 | (300 + 200) / 2 = 250 | (500 + 720) / 2 = 610 | −360 |
| P02 | (250 + 350) / 2 = 300 | (400 + 600) / 2 = 500 | −200 |
| P03 | (150 + 720) / 2 = 435 | (720 + 450) / 2 = 585 | −150 |
| P04 | (100 + 400) / 2 = 250 | (550 + 650) / 2 = 600 | −350 |
| P05 | (320 + 280) / 2 = 300 | (720 + 610) / 2 = 665 | −365 |

n = 5 (P06 has no usable baseline task); median difference −350, mean −1425 / 5 = −285. All five
differences are negative and their absolute values differ, so W = 0 and the exact two-sided
p = 2 × (1/2)^5 = 0.0625.

SUS: P01 = 2.5 × (5 × 4 + 5 × 4) = 100; P02 = 2.5 × (5 × 3 + 5 × 3) = 75; P03 = 2.5 × (5 × 2 + 5 × 2)
= 50; P04 = 2.5 × ((3 + 4 + 3 + 4 + 3) + (3 + 4 + 3 + 4 + 2)) = 82.5. P06 is not scored (sus_7 is
blank). n = 4, mean 307.5 / 4 = 76.875, median (75 + 82.5) / 2 = 78.75, sample SD √(1292.1875 / 3)
= 20.75.

Background: five questionnaires (none for P05); years of Python 1, 2, 3, 0.5, 4 → median 2;
pytest used by 3 of 5.
