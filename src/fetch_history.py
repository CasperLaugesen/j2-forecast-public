import os
import sqlite3
import requests
from dotenv import load_dotenv

load_dotenv()
KEY = os.getenv("APIFOOTBALL_KEY")
DB = "data/j2.db"


def fetch_season(season):
    r = requests.get(
        "https://v3.football.api-sports.io/fixtures",
        headers={"x-apisports-key": KEY},
        params={"league": 99, "season": season},
        timeout=30,
    )
    r.raise_for_status()                       # stopper ved HTTP-fejl
    data = r.json()
    if data["errors"]:                         # stopper ved API-fejl (din 200-lektie)
        raise RuntimeError(f"API-fejl for {season}: {data['errors']}")
    return data["response"]


def to_row(fx, season):
    return (
        fx["fixture"]["id"],
        season,
        fx["fixture"]["date"][:10],
        fx["league"]["round"],
        fx["teams"]["home"]["name"],
        fx["teams"]["away"]["name"],
        fx["goals"]["home"],
        fx["goals"]["away"],
        fx["fixture"]["status"]["short"],
    )


def main():
    os.makedirs("data", exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            fixture_id  INTEGER PRIMARY KEY,
            season      INTEGER,
            date        TEXT,
            round       TEXT,
            home        TEXT,
            away        TEXT,
            home_goals  INTEGER,
            away_goals  INTEGER,
            status      TEXT
        )
    """)
    for season in [2022, 2023, 2024]:
        rows = [to_row(fx, season) for fx in fetch_season(season)]
        con.executemany(
            "INSERT OR REPLACE INTO matches VALUES (?,?,?,?,?,?,?,?,?)", rows
        )
        print(season, len(rows), "kampe gemt")
    con.commit()
    con.close()


if __name__ == "__main__":
    main()