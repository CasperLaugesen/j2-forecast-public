"""Evaluer rapport-agenten mod de faktiske resultater.

Spørgsmålet: betyder agentens vurdering noget?
  Hvis agenten siger "explained" (nyhederne forklarer markedets syn), BURDE markedet
  oftere ramme tættere end modellen i de kampe end i kampe med "not_explained".

Data:
  report_verdicts  agentens vurderinger (gemt af save_report)
  predictions      modellens og Pinnacles sandsynligheder på det tidspunkt
  op_results       slutresultatet

Mål pr. vurdering:
  market_closer  andel af kampe, hvor markedet gav det faktiske udfald højere sandsynlighed end modellen
  logloss        model vs. marked (lavere = bedre)

Desuden: konsistens – giver agenten samme vurdering, når den har vurderet samme kamp flere gange?

Resultatet skrives til reports/evaluation.md og vises i terminalen.
Kør:  uv run python src/eval_reports.py
"""
import math
import os
import sqlite3
from datetime import datetime, timezone

import pandas as pd

DB = "data/j2.db"
OUT = "reports/evaluation.md"
MIN_N = 30          # under dette antal kampe er tallene mest støj


AGENT_RULE = ("Pre-registered rule (set 2026-10-22, before any agent forecast was scored): the agent's "
              f"forecasts only count as beating the market if their log loss is lower than the market's "
              f"over at least {MIN_N} settled matches.")


def load(con):
    cols = {r[1] for r in con.execute("PRAGMA table_info(report_verdicts)")}
    agent = ("v.agent_p1, v.agent_pX, v.agent_p2," if "agent_p1" in cols
             else "NULL AS agent_p1, NULL AS agent_pX, NULL AS agent_p2,")
    try:
        return pd.read_sql(
            f"""
            SELECT v.created_at, v.fixture_id, v.home, v.away, v.verdict, {agent}
                   p.p1, p.pX, p.p2, p.pin_p1, p.pin_pX, p.pin_p2,
                   r.home_goals, r.away_goals
            FROM report_verdicts v
            JOIN predictions p ON p.fixture_id = v.fixture_id AND p.predicted_at = v.predicted_at
            LEFT JOIN op_results r ON r.fixture_id = v.fixture_id
            """,
            con,
        )
    except pd.errors.DatabaseError:            # report_verdicts findes ikke endnu
        return pd.DataFrame()


def main():
    con = sqlite3.connect(DB)
    df = load(con)
    con.close()

    lines = [f"# Report agent – evaluation",
             f"_Updated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC_\n"]
    if df.empty:
        lines.append("No verdicts stored yet.")
        return write(lines)

    # Konsistens: samme kamp vurderet flere gange (fx to kørsler samme uge)
    multi = df.groupby("fixture_id").verdict.agg(["nunique", "size"])
    multi = multi[multi["size"] > 1]
    if len(multi):
        consistent = (multi["nunique"] == 1).mean()
        lines.append(f"**Consistency:** {len(multi)} matches judged more than once – "
                     f"same verdict every time in {consistent:.0%}.\n")

    # Mod resultaterne: brug den SENESTE vurdering pr. kamp
    latest = df.sort_values("created_at").groupby("fixture_id").tail(1)
    settled = latest.dropna(subset=["home_goals"]).copy()
    lines.append(f"**Matches judged:** {len(latest)}  |  **with result:** {len(settled)}\n")
    if settled.empty:
        lines.append("No results yet – run again after the matches.")
        return write(lines)

    def outcome(r):
        return "1" if r.home_goals > r.away_goals else "X" if r.home_goals == r.away_goals else "2"

    settled["res"] = settled.apply(outcome, axis=1)
    settled["p_model"] = settled.apply(lambda r: r["p" + r.res], axis=1)
    settled["p_market"] = settled.apply(lambda r: r["pin_p" + r.res], axis=1)
    settled["market_closer"] = settled.p_market > settled.p_model
    settled["p_agent"] = settled.apply(lambda r: r["agent_p" + r.res], axis=1)

    # Agent vs. marked – kun kampe, hvor agenten har givet sin egen forudsigelse
    a = settled.dropna(subset=["p_agent"])
    lines.append("## Can the agent beat the market?\n")
    lines.append(AGENT_RULE + "\n")
    if a.empty:
        lines.append("No settled matches with an agent forecast yet.\n")
    else:
        ll = lambda col: -a[col].astype(float).map(math.log).mean()
        lines.append("| Forecaster | Matches | Log loss |")
        lines.append("|---|---|---|")
        for name, col in [("Agent", "p_agent"), ("Market (Pinnacle)", "p_market"), ("Model", "p_model")]:
            lines.append(f"| {name} | {len(a)} | {ll(col):.3f} |")
        status = "not decided yet" if len(a) < MIN_N else (
            "agent BEATS the market" if ll("p_agent") < ll("p_market") else "agent does NOT beat the market")
        lines.append(f"\n**Status:** {status} ({len(a)}/{MIN_N} matches).\n")
    lines.append("## Do the verdicts carry information?\n")

    lines.append("| Verdict | Matches | Market closer | Log loss model | Log loss market |")
    lines.append("|---|---|---|---|---|")
    for verdict in ["explained", "partly", "not_explained", "ALL"]:
        g = settled if verdict == "ALL" else settled[settled.verdict == verdict]
        if g.empty:
            continue
        ll_model = -g.p_model.map(math.log).mean()
        ll_market = -g.p_market.map(math.log).mean()
        lines.append(f"| {verdict} | {len(g)} | {g.market_closer.mean():.0%} | "
                     f"{ll_model:.3f} | {ll_market:.3f} |")

    if len(settled) < MIN_N:
        lines.append(f"\n⚠️ Only {len(settled)} settled matches – under {MIN_N} the numbers are mostly noise.")

    lines.append("\n**How to read it:** if the agent's verdicts carry information, the market should be "
                 "closer more often in *explained* matches than in *not_explained* matches.")
    lines.append("\n## Match by match\n")
    lines.append("| Match | Verdict | Result | Model p(result) | Market p(result) | Agent p(result) |")
    lines.append("|---|---|---|---|---|---|")
    for r in settled.sort_values("created_at").itertuples():
        lines.append(f"| {r.home} – {r.away} | {r.verdict} | {int(r.home_goals)}-{int(r.away_goals)} | "
                     f"{r.p_model:.0%} | {r.p_market:.0%} | "
                     f"{'–' if pd.isna(r.p_agent) else f'{r.p_agent:.0%}'} |")
    return write(lines)


def write(lines):
    text = "\n".join(lines) + "\n"
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    main()
