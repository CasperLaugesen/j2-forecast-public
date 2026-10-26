import math
import sqlite3
import pandas as pd

DB = "data/j2.db"
K = 12           # # shrink, valgt via backtest (k=10-15 bedst)
MAX_GOALS = 10  # samme gitter som Værdispil


def load_matches(season):
    con = sqlite3.connect(DB)
    df = pd.read_sql(
        """
        SELECT date, home, away, home_goals AS hg, away_goals AS ag
        FROM matches
        WHERE season = ?
          AND round LIKE 'Regular Season%'
          AND status = 'FT'
        ORDER BY date
        """,
        con,
        params=(season,),
    )
    con.close()
    return df

def load_manual():
    con = sqlite3.connect(DB)
    df = pd.read_sql(
        "SELECT date, home, away, home_goals AS hg, away_goals AS ag FROM manual_matches",
        con,
    )
    con.close()
    return df


def load_current_season():
    """Sæsonens spillede kampe: Excel (manual_matches) + automatisk hentede (op_results).
    OddsPapi-navne oversættes med team_map. Hver kombination hjemme/ude findes kun én gang
    pr. sæson, så dubletter (samme kamp i begge kilder) fjernes på (home, away)."""
    con = sqlite3.connect(DB)
    manual = pd.read_sql(
        "SELECT date, home, away, home_goals AS hg, away_goals AS ag FROM manual_matches", con)
    try:
        auto = pd.read_sql(
            """
            SELECT substr(r.start_time, 1, 10) AS date,
                   mh.canonical AS home, ma.canonical AS away,
                   r.home_goals AS hg, r.away_goals AS ag
            FROM op_results r
            JOIN team_map mh ON mh.source = 'oddspapi' AND mh.name = r.home
            JOIN team_map ma ON ma.source = 'oddspapi' AND ma.name = r.away
            """, con)
    except pd.errors.DatabaseError:              # op_results findes ikke endnu
        auto = manual.iloc[0:0]
    con.close()
    df = pd.concat([manual, auto], ignore_index=True)
    return df.drop_duplicates(subset=["home", "away"], keep="first").reset_index(drop=True)


def team_strengths(df, k=K):
    hm, am = df["hg"].mean(), df["ag"].mean()
    avg = (hm + am) / 2
    home = df.groupby("home").agg(n_h=("hg", "size"), gf_h=("hg", "sum"), ga_h=("ag", "sum"))
    away = df.groupby("away").agg(n_a=("ag", "size"), gf_a=("ag", "sum"), ga_a=("hg", "sum"))
    t = home.join(away, how="outer").fillna(0)
    gf, ga = t.gf_h + t.gf_a, t.ga_h + t.ga_a
    exp_for = t.n_h * hm + t.n_a * am
    exp_against = t.n_h * am + t.n_a * hm
    t["att"] = (gf + k * avg) / (exp_for + k * avg)
    t["def"] = (ga + k * avg) / (exp_against + k * avg)
    return t[["att", "def"]], hm, am


def poisson(lam, x):
    return math.exp(-lam) * lam**x / math.factorial(x)


def predict(home, away, s, hm, am):
    lh = hm * s.at[home, "att"] * s.at[away, "def"]
    la = am * s.at[away, "att"] * s.at[home, "def"]
    p = {"1": 0, "X": 0, "2": 0, "Over 2,5": 0}
    for i in range(MAX_GOALS + 1):
        for j in range(MAX_GOALS + 1):
            pij = poisson(lh, i) * poisson(la, j)
            if i > j:
                p["1"] += pij
            elif i == j:
                p["X"] += pij
            else:
                p["2"] += pij
            if i + j >= 3:
                p["Over 2,5"] += pij
    p["Under 2,5"] = 1 - p["Over 2,5"]
    return lh, la, p


if __name__ == "__main__":
    df = load_matches(2024)
    print("Kampe:", len(df), "| hjemmemål/kamp:", round(df["hg"].mean(), 2),
          "| udemål/kamp:", round(df["ag"].mean(), 2))
    s, hm, am = team_strengths(df)
    print(s.sort_values("att", ascending=False).round(2).head(5))