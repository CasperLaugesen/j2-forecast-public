"""Walk-forward backtest af Poisson-modellen på J1 – sammenlignet med MARKEDET.

Spørgsmål: Slår min model Pinnacles lukkeodds?
  1) Log loss: hvem giver de bedste sandsynligheder? (lavere = bedre)
  2) Betting-simulation: hvad havde det givet at spille, når modellen så "edge"?

Kør:  uv run python src/backtest_market.py        (k = 12)
      uv run python src/backtest_market.py 6      (vælg selv k)
"""
import math
import sqlite3
import sys

import pandas as pd

from model import DB, K, team_strengths, predict

MIN_TRAIN = 100          # samme som J2-backtesten: modellen skal have set 100 kampe
OUTCOMES = ["1", "X", "2"]


def load_j1(season):
    con = sqlite3.connect(DB)
    df = pd.read_sql(
        """
        SELECT date, home, away, home_goals AS hg, away_goals AS ag,
               psch, pscd, psca, avgch, avgcd, avgca, maxch, maxcd, maxca
        FROM j1_matches
        WHERE season = ?
        ORDER BY date
        """,
        con,
        params=(season,),
    )
    con.close()
    return df


def no_vig(o1, ox, o2):
    """Odds -> sandsynligheder uden bookmakerens margin (proportional metode)."""
    inv = [1 / o1, 1 / ox, 1 / o2]
    total = sum(inv)
    return [x / total for x in inv]


def backtest(season, k=K):
    df = load_j1(season)
    rows = []
    for d in sorted(df["date"].unique()):
        train = df[df["date"] < d]                       # KUN fortiden
        if len(train) < MIN_TRAIN:
            continue
        s, hm, am = team_strengths(train, k)
        base = [(train.hg > train.ag).mean(), (train.hg == train.ag).mean(), (train.hg < train.ag).mean()]

        for m in df[df["date"] == d].itertuples():
            if m.home not in s.index or m.away not in s.index:
                continue                                  # nyt hold uden historik
            # Markedet: Pinnacle hvis muligt, ellers gennemsnitsodds
            if pd.notna(m.psch):
                mkt, src = no_vig(m.psch, m.pscd, m.psca), "pinnacle"
            elif pd.notna(m.avgch):
                mkt, src = no_vig(m.avgch, m.avgcd, m.avgca), "avg"
            else:
                continue

            _, _, p = predict(m.home, m.away, s, hm, am)
            res = "1" if m.hg > m.ag else "X" if m.hg == m.ag else "2"
            rows.append({
                "season": season, "date": d, "home": m.home, "away": m.away, "result": res,
                "p1": p["1"], "pX": p["X"], "p2": p["2"],
                "m1": mkt[0], "mX": mkt[1], "m2": mkt[2],
                "b1": base[0], "bX": base[1], "b2": base[2],
                "pin1": m.psch, "pinX": m.pscd, "pin2": m.psca,
                "max1": m.maxch, "maxX": m.maxcd, "max2": m.maxca,
                "market_src": src,
            })
    return pd.DataFrame(rows)


def logloss(bt, prefix):
    p_actual = bt.apply(lambda r: r[prefix + r["result"]], axis=1)
    return float(-p_actual.map(math.log).mean())


def simulate_bets(bt, threshold, odds_prefix):
    """Spil 1 enhed på hvert udfald, hvor model-edge > threshold.
    edge = model-sandsynlighed * odds - 1 (samme formel som i din Excel)."""
    profits = []
    for r in bt.itertuples():
        for o in OUTCOMES:
            odds = getattr(r, odds_prefix + o)
            if pd.isna(odds):
                continue
            edge = getattr(r, "p" + o) * odds - 1
            if edge > threshold:
                profits.append(odds - 1 if r.result == o else -1.0)
    if not profits:
        return 0, float("nan"), float("nan")
    s = pd.Series(profits)
    roi = s.mean()
    se = s.std() / math.sqrt(len(s))                      # usikkerhed på ROI
    return len(s), float(roi), float(se)


def main(k):
    seasons = range(2012, 2027)
    bt = pd.concat([backtest(s, k) for s in seasons], ignore_index=True)

    print(f"J1 walk-forward backtest, k = {k}, {len(bt)} kampe forudsagt\n")
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

    print("\nBETTING-SIMULATION (1 enhed pr. spil)")
    print(f"{'odds':<10}{'edge >':>8}{'spil':>7}{'ROI':>9}{'± 1 SE':>9}")
    for prefix, navn in [("pin", "Pinnacle"), ("max", "Bedste")]:
        for t in [0.0, 0.05, 0.10, 0.20]:
            n, roi, se = simulate_bets(bt, t, prefix)
            print(f"{navn:<10}{t:>8.0%}{n:>7}{roi:>+9.1%}{se:>9.1%}")

    print("\nLæsevejledning:")
    print("  model-marked > 0  -> markedet giver bedre sandsynligheder end modellen")
    print("  ROI inden for ±2 SE af 0 kan ikke skelnes fra held")
    print("  'Bedste' odds = højeste odds på tværs af bookmakere ved lukning (optimistisk)")


if __name__ == "__main__":
    k = int(sys.argv[1]) if len(sys.argv) > 1 else K
    main(k)
