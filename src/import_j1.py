"""Importer J1-kampe med lukkeodds fra football-data.co.uk (JPN.xlsx) til SQLite.

Kilde: https://www.football-data.co.uk/japan.php
Kolonner med "C" i navnet er LUKKEODDS (closing odds):
  PSC*  = Pinnacle (skarp bookmaker, bedste bud på "markedets sande mening")
  AvgC* = gennemsnit på tværs af bookmakere
  MaxC* = bedste odds på tværs af bookmakere
  *H / *D / *A = hjemmesejr / uafgjort / udesejr
"""
import sqlite3
import pandas as pd

XLSX = "data/JPN.xlsx"
DB = "data/j2.db"

ODDS_COLS = ["PSCH", "PSCD", "PSCA", "AvgCH", "AvgCD", "AvgCA", "MaxCH", "MaxCD", "MaxCA"]


def clean(raw):
    df = raw.copy()

    # 1) League findes både som "J1 League" og " J1 League" (mellemrum foran).
    #    Uden strip() ville et filter på "J1 League" miste ca. halvdelen af kampene.
    df["League"] = df["League"].str.strip()
    df = df[df["League"] == "J1 League"]

    # 2) Season blander tal (2024) og tekst ("2026/2027").
    #    Vi bruger startåret som heltal: "2026/2027" -> 2026.
    df["season"] = df["Season"].astype(str).str[:4].astype(int)

    # 3) Fjern mellemrum i holdnavne, så "Mito " og "Mito" ikke bliver to hold.
    df["Home"] = df["Home"].str.strip()
    df["Away"] = df["Away"].str.strip()

    # 4) Kun kampe med et resultat (den igangværende sæson kan have tomme rækker).
    df = df.dropna(subset=["HG", "AG"])

    out = pd.DataFrame({
        "season": df["season"],
        "date": pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d"),
        "home": df["Home"],
        "away": df["Away"],
        "home_goals": df["HG"].astype(int),
        "away_goals": df["AG"].astype(int),
    })
    for c in ODDS_COLS:
        out[c.lower()] = df[c]
    return out.sort_values(["date", "home"]).reset_index(drop=True)


def main():
    raw = pd.read_excel(XLSX)
    df = clean(raw)

    con = sqlite3.connect(DB)
    df.to_sql("j1_matches", con, if_exists="replace", index=False)
    con.close()

    print(f"{len(df)} J1-kampe importeret ({len(raw) - len(df)} rækker fravalgt)")
    summary = df.groupby("season").agg(
        kampe=("home", "size"),
        hold=("home", "nunique"),
        pinnacle_dækning=("psch", lambda s: round(s.notna().mean(), 2)),
    )
    print(summary.to_string())


if __name__ == "__main__":
    main()
