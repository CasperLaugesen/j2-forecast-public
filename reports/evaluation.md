# Report agent – evaluation
_Updated 2026-10-28 19:53 UTC_

## Model vs. market – all settled matches

| Forecaster | Matches | Log loss |
|---|---|---|
| Model | 20 | 1.157 |
| Market (Pinnacle, margin removed) | 20 | 1.097 |

Market gave the actual outcome a higher probability in 13 of 20 matches.

Backtest gap (J2 2022–24, closing odds): model 0.016 worse. Live gap so far: +0.060.

Live odds are fetched up to 4 days before kick-off, not at closing – an easier benchmark than the backtest.

⚠️ Only 20 settled matches – under 30 the numbers are mostly noise.

**Consistency (old 3-way verdict):** 6 matches judged more than once – same old 3-way verdict every time in 67%.

**Matches judged:** 7  |  **with result:** 7

## Can the agent beat the market?

Pre-registered rule (set 2026-10-22, before any agent forecast was scored): the agent's forecasts only count as beating the market if their log loss is lower than the market's over at least 30 settled matches.

| Forecaster | Matches | Log loss |
|---|---|---|
| Agent | 3 | 1.182 |
| Market (Pinnacle) | 3 | 1.114 |
| Model | 3 | 1.396 |

**Status:** not decided yet (3/30 matches).

## Does the agent pick the right side?

Pre-registered rule (set 2026-10-27, before any lean was scored): only the FIRST stored lean per match counts (re-runs never replace it), and the leans only carry information if they pick the right side more often than 'always market' over at least 30 settled matches.

No settled matches with a lean yet.

## Old 3-way verdicts (until 2026-10-26)

| Verdict | Matches | Market closer | Log loss model | Log loss market |
|---|---|---|---|---|
| partly | 5 | 60% | 1.285 | 1.248 |
| not_explained | 2 | 100% | 1.365 | 1.037 |
| ALL | 7 | 71% | 1.308 | 1.188 |

**How to read it:** if the verdicts carried information, the market should be closer more often in *explained* matches than in *not_explained* matches. Replaced by the binary lean because 13 of 15 verdicts were *partly*.

⚠️ Only 7 settled matches – under 30 the numbers are mostly noise.

## Match by match

| Match | Old verdict | Lean | Result | Model p(result) | Market p(result) | Agent p(result) |
|---|---|---|---|---|---|---|
| Albirex Niigata – Sagan Tosu | partly | – | 2-1 | 45% | 28% | – |
| Jubilo Iwata – Oita Trinita | partly | – | 0-0 | 28% | 28% | – |
| Montedio Yamagata – Consadole Sapporo | not_explained | – | 0-2 | 22% | 33% | – |
| Shonan Bellmare – Iwaki SC | partly | – | 1-1 | 26% | 28% | – |
| Oita Trinita – Ventforet Kofu | partly | – | 1-1 | 20% | 28% | 26% |
| Fujieda MYFC – Tokushima Vortis | partly | – | 0-1 | 25% | 33% | 30% |
| Montedio Yamagata – Tegevajaro Miyazaki FC | not_explained | – | 0-2 | 30% | 38% | 37% |
