"""Evaluer rapport-agenten mod de faktiske resultater.

Spørgsmålet: betyder agentens vurdering noget?
  Fra 2026-10-27: agenten siger "lean: market" eller "lean: model". Rammer den den rigtige side
  oftere end reglen "markedet har altid ret"?
  Før: explained / partly / not_explained (vises stadig, men kan ikke sammenlignes med lean).

Låst vurdering: hvert felt (lean, verdict, agentens prognose) scores fra den FØRSTE gemte række
for kampen, der har feltet. En genkørsel kan altså ikke erstatte en vurdering, der allerede er scoret.

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
LEAN_RULE = ("Pre-registered rule (set 2026-10-27, before any lean was scored): only the FIRST stored lean "
             "per match counts (re-runs never replace it), and the leans only carry information if they pick "
             f"the right side more often than 'always market' over at least {MIN_N} settled matches.")


def load(con):
    cols = {r[1] for r in con.execute("PRAGMA table_info(report_verdicts)")}
    agent = ("v.agent_p1, v.agent_pX, v.agent_p2," if "agent_p1" in cols
             else "NULL AS agent_p1, NULL AS agent_pX, NULL AS agent_p2,")
    lean = "v.lean," if "lean" in cols else "NULL AS lean,"
    try:
        return pd.read_sql(
            f"""
            SELECT v.created_at, v.fixture_id, v.home, v.away, v.verdict, {lean} {agent}
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


def load_all_settled(con):
    """Model vs. marked på ALLE afgjorte kampe – ikke kun dem, agenten har vurderet.

    Pr. kamp bruges den SENESTE forudsigelse før kickoff. Forudsigelser efter kickoff tæller aldrig.
    Pinnacles sandsynligheder normaliseres til 1 (margin fjernet), før der scores.
    """
    try:
        df = pd.read_sql(
            """
            SELECT p.fixture_id, p.home, p.away, r.start_time, p.predicted_at,
                   p.p1, p.pX, p.p2, p.pin_p1, p.pin_pX, p.pin_p2,
                   r.home_goals, r.away_goals
            FROM predictions p
            JOIN op_results r ON r.fixture_id = p.fixture_id
            WHERE r.home_goals IS NOT NULL AND r.away_goals IS NOT NULL
              AND p.pin_p1 IS NOT NULL AND p.pin_pX IS NOT NULL AND p.pin_p2 IS NOT NULL
            """,
            con,
        )
    except pd.errors.DatabaseError:            # predictions/op_results findes ikke endnu
        return pd.DataFrame()

    cols = ["fixture_id", "home", "away", "start_time", "p_model", "p_market"]
    # Tidspunkter sammenlignes som datoer, ikke tekst ("...04:00:00" vs. "...04:00:00.000Z")
    df = df[pd.to_datetime(df.predicted_at, utc=True) < pd.to_datetime(df.start_time, utc=True)]
    if df.empty:
        return pd.DataFrame(columns=cols)
    df = df.sort_values("predicted_at", kind="stable").groupby("fixture_id").tail(1).copy()

    df["res"] = df.apply(lambda r: "1" if r.home_goals > r.away_goals
                         else "X" if r.home_goals == r.away_goals else "2", axis=1)
    df["p_model"] = df.apply(lambda r: r["p" + r.res], axis=1)
    df["p_market"] = (df.apply(lambda r: r["pin_p" + r.res], axis=1)
                      / (df.pin_p1 + df.pin_pX + df.pin_p2))
    return df[cols].sort_values("start_time").reset_index(drop=True)


def first_per_fixture(df, col):
    """Den første gemte række pr. kamp, hvor `col` er udfyldt. Senere genkørsler ignoreres."""
    return (df.dropna(subset=[col]).sort_values("created_at", kind="stable")
            .groupby("fixture_id").head(1))


def main():
    con = sqlite3.connect(DB)
    df = load(con)
    allm = load_all_settled(con)
    con.close()

    lines = [f"# Report agent – evaluation",
             f"_Updated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC_\n"]

    # Model vs. marked på alle afgjorte kampe: holder backtestens gap live?
    lines.append("## Model vs. market – all settled matches\n")
    if allm.empty:
        lines.append("No settled matches with a prediction before kick-off yet.\n")
    else:
        n = len(allm)
        ll_model = -allm.p_model.map(math.log).mean()
        ll_market = -allm.p_market.map(math.log).mean()
        lines.append("| Forecaster | Matches | Log loss |")
        lines.append("|---|---|---|")
        lines.append(f"| Model | {n} | {ll_model:.3f} |")
        lines.append(f"| Market (Pinnacle, margin removed) | {n} | {ll_market:.3f} |")
        lines.append(f"\nMarket gave the actual outcome a higher probability in "
                     f"{(allm.p_market > allm.p_model).sum()} of {n} matches.\n")
        lines.append(f"Backtest gap (J2 2022–24, closing odds): model 0.016 worse. "
                     f"Live gap so far: {ll_model - ll_market:+.3f}.\n")
        lines.append("Live odds are fetched up to 4 days before kick-off, not at closing – "
                     "an easier benchmark than the backtest.\n")
        if n < MIN_N:
            lines.append(f"⚠️ Only {n} settled matches – under {MIN_N} the numbers are mostly noise.\n")

    if df.empty:
        lines.append("No verdicts stored yet.")
        return write(lines)

    # Konsistens: samme kamp vurderet flere gange (fx genkørsler samme dag)
    for col, name in [("lean", "lean"), ("verdict", "old 3-way verdict")]:
        multi = df.dropna(subset=[col]).groupby("fixture_id")[col].agg(["nunique", "size"])
        multi = multi[multi["size"] > 1]
        if len(multi):
            lines.append(f"**Consistency ({name}):** {len(multi)} matches judged more than once – "
                         f"same {name} every time in {(multi['nunique'] == 1).mean():.0%}.\n")

    # Mod resultaterne: hvert felt fra den FØRSTE række, der har det (se first_per_fixture)
    settled = df.dropna(subset=["home_goals"]).copy()
    lines.append(f"**Matches judged:** {df.fixture_id.nunique()}  |  "
                 f"**with result:** {settled.fixture_id.nunique()}\n")
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
    a = first_per_fixture(settled, "p_agent")
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

    # Binært lean: rammer agenten den rigtige side oftere end "markedet har altid ret"?
    lean = first_per_fixture(settled, "lean")
    lines.append("## Does the agent pick the right side?\n")
    lines.append(LEAN_RULE + "\n")
    if lean.empty:
        lines.append("No settled matches with a lean yet.\n")
    else:
        right = (lean.lean == "market") == lean.market_closer
        lines.append("| Rule | Matches | Right side |")
        lines.append("|---|---|---|")
        lines.append(f"| Agent's lean ({(lean.lean == 'market').sum()} market, {(lean.lean == 'model').sum()} model) "
                     f"| {len(lean)} | {right.mean():.0%} |")
        lines.append(f"| Always market | {len(lean)} | {lean.market_closer.mean():.0%} |")
        status = "not decided yet" if len(lean) < MIN_N else (
            "leans carry information" if right.mean() > lean.market_closer.mean()
            else "leans do NOT beat 'always market'")
        lines.append(f"\n**Status:** {status} ({len(lean)}/{MIN_N} matches).\n")

    old = first_per_fixture(settled, "verdict")
    if not old.empty:
        lines.append("## Old 3-way verdicts (until 2026-10-26)\n")
        lines.append("| Verdict | Matches | Market closer | Log loss model | Log loss market |")
        lines.append("|---|---|---|---|---|")
        for verdict in ["explained", "partly", "not_explained", "ALL"]:
            g = old if verdict == "ALL" else old[old.verdict == verdict]
            if g.empty:
                continue
            ll_model = -g.p_model.map(math.log).mean()
            ll_market = -g.p_market.map(math.log).mean()
            lines.append(f"| {verdict} | {len(g)} | {g.market_closer.mean():.0%} | "
                         f"{ll_model:.3f} | {ll_market:.3f} |")
        lines.append("\n**How to read it:** if the verdicts carried information, the market should be "
                     "closer more often in *explained* matches than in *not_explained* matches. "
                     "Replaced by the binary lean because 13 of 15 verdicts were *partly*.")

    n_settled = settled.fixture_id.nunique()
    if n_settled < MIN_N:
        lines.append(f"\n⚠️ Only {n_settled} settled matches – under {MIN_N} the numbers are mostly noise.")

    lines.append("\n## Match by match\n")
    lines.append("| Match | Old verdict | Lean | Result | Model p(result) | Market p(result) | Agent p(result) |")
    lines.append("|---|---|---|---|---|---|---|")
    leans = lean.set_index("fixture_id").lean
    verdicts = old.set_index("fixture_id").verdict
    agent_p = a.set_index("fixture_id").p_agent
    for r in first_per_fixture(settled, "created_at").itertuples():
        p_ag = agent_p.get(r.fixture_id)
        lines.append(f"| {r.home} – {r.away} | {verdicts.get(r.fixture_id, '–')} | {leans.get(r.fixture_id, '–')} "
                     f"| {int(r.home_goals)}-{int(r.away_goals)} | {r.p_model:.0%} | {r.p_market:.0%} | "
                     f"{'–' if p_ag is None else f'{p_ag:.0%}'} |")
    return write(lines)


def write(lines):
    text = "\n".join(lines) + "\n"
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    main()
