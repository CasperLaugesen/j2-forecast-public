"""Walk-forward backtest på J2 2022-2024 mod CheckBestOdds-odds.

Samme metode som backtest_market.py (J1 mod Pinnacle), men:
  - resultater fra API-Football (tabellen matches)
  - odds fra CheckBestOdds (tabellen cbo_j2, lavet af parse_cbo.py)

Forbehold: CheckBestOdds-oddsene er "sidst registrerede højeste odds" fra et ukendt
udvalg af bookmakere – en SVAGERE målestok end Pinnacle-lukkeodds.

Kør:  uv run python src/backtest_j2_market.py        (k = 12)
      uv run python src/backtest_j2_market.py 6
"""
import sqlite3
import sys

import pandas as pd

from model import DB, K, team_strengths, predict
from backtest_market import MIN_TRAIN, OUTCOMES, no_vig, logloss, simulate_bets


def load_j2_with_odds(season):
    con = sqlite3.connect(DB)
    df = pd.read_sql(
        """
        SELECT m.date, m.home, m.away, m.home_goals AS hg, m.away_goals AS ag,
               c.odds_1, c.odds_x, c.odds_2
        FROM matches m
        LEFT JOIN cbo_j2 c
          ON c.season = m.season AND c.home = m.home AND c.away = m.away
        WHERE m.season = ?
          AND m.round LIKE 'Regular Season%'
          AND m.status = 'FT'
        ORDER BY m.date
        """,
        con,
        params=(season,),
    )
    con.close()
    return df


def backtest(season, k=K):
    df = load_j2_with_odds(season)
    rows = []
    for d in sorted(df["date"].unique()):
        train = df[df["date"] < d]                    # KUN fortiden (alle kampe, også uden odds)
        if len(train) < MIN_TRAIN:
            continue
        s, hm, am = team_strengths(train, k)
        base = [(train.hg > train.ag).mean(), (train.hg == train.ag).mean(), (train.hg < train.ag).mean()]

        for m in df[df["date"] == d].itertuples():
            if pd.isna(m.odds_1) or m.home not in s.index or m.away not in s.index:
                continue                               # evaluer kun kampe med odds
            mkt = no_vig(m.odds_1, m.odds_x, m.odds_2)
            _, _, p = predict(m.home, m.away, s, hm, am)
            res = "1" if m.hg > m.ag else "X" if m.hg == m.ag else "2"
            rows.append({
                "season": season, "date": d, "home": m.home, "away": m.away, "result": res,
                "p1": p["1"], "pX": p["X"], "p2": p["2"],
                "m1": mkt[0], "mX": mkt[1], "m2": mkt[2],
                "b1": base[0], "bX": base[1], "b2": base[2],
                "cbo1": m.odds_1, "cboX": m.odds_x, "cbo2": m.odds_2,
                "margin": 1 / m.odds_1 + 1 / m.odds_x + 1 / m.odds_2 - 1,
            })
    return pd.DataFrame(rows)


def main(k):
    bt = pd.concat([backtest(s, k) for s in [2022, 2023, 2024]], ignore_index=True)

    print(f"J2 walk-forward backtest mod CheckBestOdds, k = {k}, {len(bt)} kampe forudsagt")
    print(f"Gns. bookmaker-margin i oddsene: {bt.margin.mean():.1%}\n")
    print("LOG LOSS PR. SÆSON (lavere = bedre)")
    print(f"{'sæson':<7}{'kampe':>6}{'model':>9}{'marked':>9}{'baseline':>10}{'model-marked':>14}")
    for season, g in bt.groupby("season"):
        lm, lk, lb = logloss(g, "p"), logloss(g, "m"), logloss(g, "b")
        print(f"{season:<7}{len(g):>6}{lm:>9.4f}{lk:>9.4f}{lb:>10.4f}{lm - lk:>+14.4f}")
    lm, lk, lb = logloss(bt, "p"), logloss(bt, "m"), logloss(bt, "b")
    print(f"{'ALLE':<7}{len(bt):>6}{lm:>9.4f}{lk:>9.4f}{lb:>10.4f}{lm - lk:>+14.4f}")

    print("\nSKÆVHED: gennemsnitlig sandsynlighed")
    for o, navn in zip(OUTCOMES, ["hjemmesejr", "uafgjort", "udesejr"]):
        print(f"  {navn:<11} model {bt['p' + o].mean():.1%}   marked {bt['m' + o].mean():.1%}"
              f"   faktisk {(bt.result == o).mean():.1%}")

    print("\nBETTING-SIMULATION (1 enhed pr. spil, CheckBestOdds-odds)")
    print(f"{'edge >':>8}{'spil':>7}{'ROI':>9}{'± 1 SE':>9}")
    for t in [0.0, 0.05, 0.10, 0.20]:
        n, roi, se = simulate_bets(bt, t, "cbo")
        print(f"{t:>8.0%}{n:>7}{roi:>+9.1%}{se:>9.1%}")


if __name__ == "__main__":
    k = int(sys.argv[1]) if len(sys.argv) > 1 else K
    main(k)
