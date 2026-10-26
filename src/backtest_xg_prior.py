"""Opfølgning: hjælper sidste sæsons xG som udgangspunkt (prior)? Forhåndsregistreret i README, afsnit 6.

Nuværende model: shrinkage trækker hvert holds rating mod 1,00 (ligagennemsnit).
Variant:         shrinkage trækker mod holdets xG-rating fra SIDSTE sæson (kendt før sæsonstart,
                 så ingen look-ahead bias). Hold uden J2-sæson året før får 1,00.

Data: data/xg_season.csv (klub-xG/xGA pr. sæson fra J.Leagues officielle statistiksider,
indsamlet én gang manuelt; ikke med i repoet pga. J.Leagues vilkår).

Kør:  uv run python src/backtest_xg_prior.py
"""
import math
import sqlite3

import numpy as np
import pandas as pd

from model import DB, K, load_matches, predict

XG_CSV = "data/xg_season.csv"
TEST_SEASONS = [2023, 2024]
PRIMARY_MIN_TRAIN = 20       # primær sammenligning: fra 20 spillede kampe
SECONDARY_MIN_TRAIN = 100    # sekundær: den oprindelige opsætning
THRESHOLD = 0.005            # beslutningsregel: varianten skal være mindst 0,005 bedre


def xg_priors(prev_season):
    """Hvert holds xG- og xGA-rating fra sæsonen før: (pr. kamp) / (ligagennemsnit pr. kamp)."""
    xg = pd.read_csv(XG_CSV)
    xg = xg[xg.season == prev_season].set_index("team")
    games = load_matches(prev_season)
    n = pd.concat([games.home, games.away]).value_counts()
    xg["n"] = n.reindex(xg.index)
    assert xg["n"].notna().all(), "hold i xG-data mangler i kampdata"
    att = (xg.xg / xg.n) / (xg.xg.sum() / xg.n.sum())
    dfn = (xg.xga / xg.n) / (xg.xga.sum() / xg.n.sum())
    return att.to_dict(), dfn.to_dict()


def team_strengths_prior(df, k, prior_att, prior_def):
    """Som model.team_strengths, men shrinkage trækker mod prior i stedet for 1,00.
    Med prior = 1,00 for alle hold giver den præcis den nuværende model."""
    hm, am = df["hg"].mean(), df["ag"].mean()
    avg = (hm + am) / 2
    home = df.groupby("home").agg(n_h=("hg", "size"), gf_h=("hg", "sum"), ga_h=("ag", "sum"))
    away = df.groupby("away").agg(n_a=("ag", "size"), gf_a=("ag", "sum"), ga_a=("hg", "sum"))
    t = home.join(away, how="outer").fillna(0)
    gf, ga = t.gf_h + t.gf_a, t.ga_h + t.ga_a
    exp_for = t.n_h * hm + t.n_a * am
    exp_against = t.n_h * am + t.n_a * hm
    pa = t.index.map(lambda x: prior_att.get(x, 1.0)).to_numpy()
    pd_ = t.index.map(lambda x: prior_def.get(x, 1.0)).to_numpy()
    t["att"] = (gf + k * avg * pa) / (exp_for + k * avg)
    t["def"] = (ga + k * avg * pd_) / (exp_against + k * avg)
    return t[["att", "def"]], hm, am


def market_probs(season):
    con = sqlite3.connect(DB)
    o = pd.read_sql("SELECT home, away, odds_1, odds_x, odds_2 FROM cbo_j2 WHERE season = ?",
                    con, params=(season,))
    con.close()
    inv = 1 / o[["odds_1", "odds_x", "odds_2"]]
    p = inv.div(inv.sum(axis=1), axis=0)
    p.columns = ["m1", "mX", "m2"]
    return pd.concat([o[["home", "away"]], p], axis=1)


def backtest(season, k=K):
    df = load_matches(season)
    prior_att, prior_def = xg_priors(season - 1)
    rows = []
    for d in sorted(df["date"].unique()):
        train = df[df["date"] < d]                       # KUN fortiden
        if len(train) < PRIMARY_MIN_TRAIN:
            continue
        flat = team_strengths_prior(train, k, {}, {})    # = nuværende model
        xgp = team_strengths_prior(train, k, prior_att, prior_def)
        for m in df[df["date"] == d].itertuples():
            if m.home not in flat[0].index or m.away not in flat[0].index:
                continue                                  # samme kampe for begge modeller
            _, _, p0 = predict(m.home, m.away, *flat)
            _, _, p1 = predict(m.home, m.away, *xgp)
            res = "1" if m.hg > m.ag else "X" if m.hg == m.ag else "2"
            rows.append({"season": season, "date": d, "n_train": len(train),
                         "home": m.home, "away": m.away, "result": res,
                         "cur": p0[res], "xgp": p1[res],
                         "home_prior": m.home in prior_att, "away_prior": m.away in prior_att})
    bt = pd.DataFrame(rows)
    mkt = market_probs(season)
    bt = bt.merge(mkt, on=["home", "away"], how="left")
    bt["mkt"] = bt.apply(lambda r: r["m" + r["result"]] if pd.notna(r["m1"]) else np.nan, axis=1)
    return bt


def ll(p):
    return float(-np.log(p).mean())


def report(bt, label):
    d = -np.log(bt.xgp) + np.log(bt.cur)                  # < 0: xG-prior bedre
    se = d.std(ddof=1) / math.sqrt(len(d))
    print(f"\n{label}: {len(bt)} kampe")
    print(f"  Nuværende model : {ll(bt.cur):.4f}")
    print(f"  xG-prior        : {ll(bt.xgp):.4f}")
    print(f"  Forskel (xG − nuværende): {d.mean():+.4f}  (± 1 SE {se:.4f})")
    wm = bt.dropna(subset=["mkt"])
    print(f"  Med odds ({len(wm)} kampe): nuværende {ll(wm.cur):.4f} | xG-prior {ll(wm.xgp):.4f}"
          f" | marked {ll(wm.mkt):.4f}")
    return d.mean()


if __name__ == "__main__":
    bt = pd.concat([backtest(s) for s in TEST_SEASONS], ignore_index=True)

    diff = report(bt, "PRIMÆR – 2023-2024, fra 20 spillede kampe")
    for s in TEST_SEASONS:
        report(bt[bt.season == s], f"  {s}")
    report(bt[bt.n_train >= SECONDARY_MIN_TRAIN], "SEKUNDÆR – fra 100 spillede kampe")

    print("\nLog loss efter hvor langt sæsonen er (begge sæsoner):")
    bins = [20, 100, 200, 300, 500]
    bt["fase"] = pd.cut(bt.n_train, bins=bins, right=False)
    print(bt.groupby("fase", observed=True).apply(
        lambda g: pd.Series({"kampe": len(g), "nuværende": ll(g.cur), "xG-prior": ll(g.xgp)})
    ).round(4).to_string())

    verdict = "FORBEDRING" if diff <= -THRESHOLD else "INGEN FORBEDRING"
    print(f"\nBeslutningsregel (≥ {THRESHOLD} bedre): {diff:+.4f} → {verdict}")
