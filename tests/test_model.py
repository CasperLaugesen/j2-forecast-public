"""Tests af Poisson-modellen. Kør:  uv run pytest"""
import random

import pandas as pd
import pytest

from backtest_market import no_vig, walk_forward
from model import predict, team_strengths


def test_probabilities_sum_to_one():
    # Lav to hold i hånden i stedet for at læse databasen:
    # A er et stærkt hold, B et svagt (ratings relativt til ligagennemsnit 1.00).
    s = pd.DataFrame({"att": [1.4, 0.8], "def": [0.7, 1.3]}, index=["A", "B"])
    hm, am = 1.4, 1.1                      # ligagennemsnit hjemme-/udemål

    _, _, p = predict("A", "B", s, hm, am)

    # Ikke præcis 1: gitteret stopper ved 10 mål, så lidt sandsynlighed "forsvinder"
    # (ca. 0.00007 ved λ = 2.5). Det er for lidt til at påvirke log loss-konklusionen.
    assert p["1"] + p["X"] + p["2"] == pytest.approx(1, abs=1e-3)
    assert p["1"] > p["2"]                 # det stærke hjemmehold skal være favorit


# TODO (Casper): test 2 – no_vig(2.0, 3.5, 4.0) summerer til 1 og favoritten er størst
def test_no_vig_removes_margin():
    odds = (2.0, 3.5, 4.0)                      # hjemme, uafgjort, ude
    p = no_vig(*odds)

    assert sum(p) == pytest.approx(1)           # rigtige sandsynligheder summerer til 1
    assert p[0] > p[1] and p[0] > p[2]          # laveste odds = favorit
    for prob, o in zip(p, odds):
        assert prob < 1 / o    



# TODO (Casper): test 3 – shrinkage: én 4-0-sejr giver att tæt på 1 med k=12, højt med k=0
def test_shrinkage_pulls_towards_average():
    # 6 "normale" 1-1-kampe mellem andre hold, så ligagennemsnittet er realistisk.
    # Uden dem ville As 4-0 selv VÆRE ligagennemsnittet, og att ville blive 1.0 uanset k.
    kampe = [("C", "D", 1, 1), ("E", "F", 1, 1), ("D", "E", 1, 1),
             ("F", "C", 1, 1), ("C", "E", 1, 1), ("D", "F", 1, 1),
             ("A", "B", 4, 0)]                    # A: én kamp, vandt 4-0
    df = pd.DataFrame(kampe, columns=["home", "away", "hg", "ag"])

    uden, _, _ = team_strengths(df, k=0)
    med, _, _ = team_strengths(df, k=12)

    assert uden.at["A", "att"] > 2                # k=0: én kamp -> ekstrem rating (2.8)
    assert 1 < med.at["A", "att"] < 1.3           # k=12: trukket mod 1.00 (1.17)
    assert uden.at["A", "def"] == 0               # k=0: "perfekt forsvar" efter én clean sheet
    assert med.at["A", "def"] > 0.8               # k=12: realistisk (0.94)


def lav_saeson(n_dage=20, seed=1):
    """Falsk sæson: 6 hold, 3 kampe pr. dag, tilfældige resultater, faste odds."""
    rng = random.Random(seed)
    hold = ["A", "B", "C", "D", "E", "F"]
    kampe = []
    for dag in range(n_dage):
        rng.shuffle(hold)
        for i in range(0, 6, 2):
            kampe.append({"date": f"2024-03-{dag + 1:02d}", "home": hold[i], "away": hold[i + 1],
                          "hg": rng.randint(0, 3), "ag": rng.randint(0, 3),
                          "psch": 2.5, "pscd": 3.3, "psca": 3.0,
                          "avgch": None, "avgcd": None, "avgca": None,
                          "maxch": 2.6, "maxcd": 3.4, "maxca": 3.1})
    return pd.DataFrame(kampe)


def test_no_look_ahead(monkeypatch):
    import backtest_market
    monkeypatch.setattr(backtest_market, "MIN_TRAIN", 15)   # små falske data -> lavere krav

    df = lav_saeson()
    skillelinje = "2024-03-15"

    # Version 2: samme sæson, men alle kampe FRA skillelinjen ændres til absurde 9-0-sejre.
    fremtid_aendret = df.copy()
    senere = fremtid_aendret["date"] >= skillelinje
    fremtid_aendret.loc[senere, ["hg", "ag"]] = [9, 0]

    a = walk_forward(df, 2024, k=12)
    b = walk_forward(fremtid_aendret, 2024, k=12)

    # Forudsigelser TIL OG MED skillelinjen må ikke ændre sig, når fremtiden ændres.
    # (Kampdagen selv er med: modellen må heller ikke kende resultaterne fra samme dag.)
    for_a = a[a["date"] <= skillelinje][["p1", "pX", "p2"]].reset_index(drop=True)
    for_b = b[b["date"] <= skillelinje][["p1", "pX", "p2"]].reset_index(drop=True)
    assert len(for_a) > 0
    pd.testing.assert_frame_equal(for_a, for_b)

    # Kontrol: testen kan faktisk se forskel – efter skillelinjen SKAL de ændre sig.
    efter_a = a[a["date"] > skillelinje]["p1"].reset_index(drop=True)
    efter_b = b[b["date"] > skillelinje]["p1"].reset_index(drop=True)
    assert not efter_a.equals(efter_b)