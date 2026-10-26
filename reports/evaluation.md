# Report agent – evaluation
_Updated 2026-10-26 11:10 UTC_

**Consistency:** 6 matches judged more than once – same verdict every time in 67%.

**Matches judged:** 7  |  **with result:** 7

## Can the agent beat the market?

Pre-registered rule (set 2026-10-22, before any agent forecast was scored): the agent's forecasts only count as beating the market if their log loss is lower than the market's over at least 30 settled matches.

| Forecaster | Matches | Log loss |
|---|---|---|
| Agent | 3 | 1.182 |
| Market (Pinnacle) | 3 | 1.114 |
| Model | 3 | 1.396 |

**Status:** not decided yet (3/30 matches).

## Do the verdicts carry information?

| Verdict | Matches | Market closer | Log loss model | Log loss market |
|---|---|---|---|---|
| partly | 7 | 71% | 1.308 | 1.188 |
| ALL | 7 | 71% | 1.308 | 1.188 |

⚠️ Only 7 settled matches – under 30 the numbers are mostly noise.

**How to read it:** if the agent's verdicts carry information, the market should be closer more often in *explained* matches than in *not_explained* matches.

## Match by match

| Match | Verdict | Result | Model p(result) | Market p(result) | Agent p(result) |
|---|---|---|---|---|---|
| Montedio Yamagata – Consadole Sapporo | partly | 0-2 | 22% | 33% | – |
| Albirex Niigata – Sagan Tosu | partly | 2-1 | 45% | 28% | – |
| Jubilo Iwata – Oita Trinita | partly | 0-0 | 28% | 28% | – |
| Shonan Bellmare – Iwaki SC | partly | 1-1 | 26% | 28% | – |
| Oita Trinita – Ventforet Kofu | partly | 1-1 | 20% | 28% | 26% |
| Fujieda MYFC – Tokushima Vortis | partly | 0-1 | 25% | 33% | 30% |
| Montedio Yamagata – Tegevajaro Miyazaki FC | partly | 0-2 | 30% | 38% | 37% |
