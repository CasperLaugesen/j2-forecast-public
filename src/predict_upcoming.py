"""Forudsig kommende J2-kampe (fra OddsPapi) og sammenlign med Pinnacle og Mr Green.

Kæden:
  manual_matches + op_results (spillede kampe) -> team_strengths  (modellen)
  op_fixtures + team_map                      -> kommende kampe med modellens holdnavne
  odds_snapshots (seneste pr. bookmaker)      -> markedets sandsynligheder

Alt gemmes i tabellen `predictions` med tidspunkt og modelversion, så du altid kan se,
hvad modellen sagde FØR kampen (løser logbogsproblemet med blandede modelversioner).

Kør:  uv run python src/predict_upcoming.py
"""
import sqlite3
from datetime import datetime, timezone

import pandas as pd

from model import DB, K, load_current_season, team_strengths, predict
from backtest_market import no_vig

SHARP, RETAIL = "pinnacle", "mrgreen.dk"


def load_upcoming(con, now_iso):
    """Kommende kampe med kanoniske holdnavne + seneste odds fra hver bookmaker."""
    return pd.read_sql(
        """
        WITH latest AS (
            SELECT fixture_id, bookmaker, MAX(snapshot_at) AS snapshot_at
            FROM odds_snapshots
            GROUP BY fixture_id, bookmaker
        )
        SELECT f.fixture_id, f.start_time,
               mh.canonical AS home, ma.canonical AS away,
               s.bookmaker, s.odds_1, s.odds_x, s.odds_2, s.snapshot_at
        FROM op_fixtures f
        JOIN team_map mh ON mh.source = 'oddspapi' AND mh.name = f.home
        JOIN team_map ma ON ma.source = 'oddspapi' AND ma.name = f.away
        JOIN latest l    ON l.fixture_id = f.fixture_id
        JOIN odds_snapshots s
             ON s.fixture_id = l.fixture_id AND s.bookmaker = l.bookmaker AND s.snapshot_at = l.snapshot_at
        WHERE f.start_time > ?
        ORDER BY f.start_time, f.fixture_id
        """,
        con,
        params=(now_iso,),
    )


def main(k=K):
    now = datetime.now(timezone.utc)
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%S")
    train = load_current_season()                         # Excel-runder + automatisk hentede resultater
    s, hm, am = team_strengths(train, k)
    model_version = f"poisson_k{k}_n{len(train)}"          # hvad modellen er trænet på

    con = sqlite3.connect(DB)
    odds = load_upcoming(con, now_iso)
    if odds.empty:
        print("Ingen kommende kampe med odds. Kør fetch_weekly.py først (og name_agent.py ved nye hold).")
        return

    rows = []
    for fid, g in odds.groupby("fixture_id", sort=False):
        first = g.iloc[0]
        _, _, p = predict(first.home, first.away, s, hm, am)
        row = {
            "predicted_at": now_iso, "model_version": model_version, "fixture_id": fid,
            "start_time": first.start_time, "home": first.home, "away": first.away,
            "p1": p["1"], "pX": p["X"], "p2": p["2"],
        }
        for bm, tag in [(SHARP, "pin"), (RETAIL, "mg")]:
            b = g[g.bookmaker == bm]
            if b.empty:
                row.update({f"{tag}_odds_{o}": None for o in "1X2"})
                row.update({f"{tag}_p{o}": None for o in "1X2"})
                continue
            b = b.iloc[0]
            m = no_vig(b.odds_1, b.odds_x, b.odds_2)
            row.update({f"{tag}_odds_1": b.odds_1, f"{tag}_odds_X": b.odds_x, f"{tag}_odds_2": b.odds_2,
                        f"{tag}_p1": m[0], f"{tag}_pX": m[1], f"{tag}_p2": m[2]})
        rows.append(row)

    df = pd.DataFrame(rows)
    df.to_sql("predictions", con, if_exists="append", index=False)
    con.close()

    # Uenighed: største afstand mellem model og Pinnacle på tværs af 1/X/2 (procentpoint)
    df["disagree"] = df.apply(
        lambda r: max(abs(r[f"p{o}"] - r[f"pin_p{o}"]) for o in "1X2") if pd.notna(r["pin_p1"]) else None,
        axis=1,
    )
    show = df.sort_values("disagree", ascending=False)
    pd.set_option("display.width", 200)
    print(f"Model: {model_version}  |  {len(df)} kampe gemt i predictions ({now_iso} UTC)\n")
    print(show[["home", "away", "p1", "pin_p1", "pX", "pin_pX", "p2", "pin_p2", "disagree"]]
          .round(3).to_string(index=False))
    print("\np = model, pin_p = Pinnacle uden margin. Sorteret efter størst uenighed.")


if __name__ == "__main__":
    main()
