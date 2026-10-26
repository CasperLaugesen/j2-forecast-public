import sys
import sqlite3
import pandas as pd
from model import DB, load_manual, team_strengths, predict


def no_vig(o1, ox, o2):
    inv = [1 / o1, 1 / ox, 1 / o2]
    total = sum(inv)                     # > 1 pga. bookmakerens marginal
    return [x / total for x in inv]


def main(k):
    s, hm, am = team_strengths(load_manual(), k)
    con = sqlite3.connect(DB)
    fx = pd.read_sql("SELECT * FROM fixtures", con)
    con.close()

    rows = []
    for f in fx.itertuples():
        lh, la, p = predict(f.home, f.away, s, hm, am)
        m1, mx, m2 = no_vig(f.odds_1, f.odds_x, f.odds_2)
        rows.append({
            "kamp": f"{f.home} - {f.away}",
            "λh": lh, "λu": la,
            "P1": p["1"], "M1": m1,
            "PX": p["X"], "MX": mx,
            "P2": p["2"], "M2": m2,
            "POver": p["Over 2,5"],
            "edge1": p["1"] * f.odds_1 - 1,
            "edgeX": p["X"] * f.odds_x - 1,
            "edge2": p["2"] * f.odds_2 - 1,
            "edgeO": p["Over 2,5"] * f.odds_over25 - 1,
        })
    pd.set_option("display.width", 250)
    print(f"k = {k}")
    print(pd.DataFrame(rows).round(3).to_string(index=False))


if __name__ == "__main__":
    k = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    main(k)