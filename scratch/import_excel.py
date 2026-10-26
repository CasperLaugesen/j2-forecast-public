import sqlite3
import pandas as pd

XLSX = "data/k2.xlsx"
DB = "data/j2.db"


def main():
    kampe = pd.read_excel(XLSX, sheet_name="Kampe", usecols="A:E")
    kampe.columns = ["date", "home", "home_goals", "away_goals", "away"]
    kampe = kampe.dropna(subset=["home"])

    fx = pd.read_excel(XLSX, sheet_name="Værdispil", usecols="J:Q", skiprows=9, nrows=10)
    fx.columns = ["home", "away", "kickoff",
                  "odds_1", "odds_x", "odds_2", "odds_over25", "odds_under25"]

    con = sqlite3.connect(DB)
    kampe.to_sql("manual_matches", con, if_exists="replace", index=False)
    fx.to_sql("fixtures", con, if_exists="replace", index=False)
    con.close()
    print(len(kampe), "spillede kampe og", len(fx), "kommende kampe importeret")


if __name__ == "__main__":
    main()