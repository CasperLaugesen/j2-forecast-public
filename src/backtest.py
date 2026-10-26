import math
import pandas as pd
from model import load_matches, team_strengths, predict

MIN_TRAIN = 100   # samme datamængde som din Excel-model har nu


def backtest(season, k=6):
    df = load_matches(season)
    rows = []
    for d in sorted(df["date"].unique()):
        train = df[df["date"] < d]              # KUN fortiden
        if len(train) < MIN_TRAIN:
            continue
        s, hm, am = team_strengths(train, k)
        base = {                                 # naiv model: bare ligaens fordeling
            "1": (train.hg > train.ag).mean(),
            "X": (train.hg == train.ag).mean(),
            "2": (train.hg < train.ag).mean(),
        }
        for m in df[df["date"] == d].itertuples():
            _, _, p = predict(m.home, m.away, s, hm, am)
            res = "1" if m.hg > m.ag else "X" if m.hg == m.ag else "2"
            rows.append({
                "date": d, "home": m.home, "away": m.away, "result": res,
                "p1": p["1"], "pX": p["X"], "p2": p["2"],
                "b1": base["1"], "bX": base["X"], "b2": base["2"],
            })
    return pd.DataFrame(rows)


def scores(bt, prefix):
    brier = sum((bt[prefix + k] - (bt["result"] == k)) ** 2 for k in ["1", "X", "2"]).mean()
    p_actual = bt.apply(lambda r: r[prefix + r["result"]], axis=1)
    logloss = -p_actual.map(math.log).mean()
    return round(float(brier), 4), round(float(logloss), 4)


if __name__ == "__main__":
    for season in [2022, 2023, 2024]:
        bt = backtest(season)
        print(f"\n{season}: {len(bt)} kampe forudsagt")
        print("  Model     (Brier, LogLoss):", scores(bt, "p"))
        print("  Baseline  (Brier, LogLoss):", scores(bt, "b"))
        print(f"  Uafgjort: model forudsiger {bt.pX.mean():.1%}, faktisk {(bt.result == 'X').mean():.1%}")

    print("\nk   LogLoss (gns. 2022-2024)")
    for k in [0, 3, 6, 10, 15, 25, 40]:
        losses = [scores(backtest(season, k), "p")[1] for season in [2022, 2023, 2024]]
        print(f"{k:<3} {float(sum(losses) / len(losses)):.4f}")