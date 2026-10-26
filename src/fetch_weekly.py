"""Hent kommende J2-kampe og 1X2-odds fra OddsPapi og gem dem i SQLite.

Erstatter den manuelle indtastning af odds i Excel. Kører ugentligt (senere automatisk).

Tabeller:
  op_fixtures     én række pr. kamp (opdateres, hvis kampen flyttes)
  odds_snapshots  én række pr. kamp × bookmaker × hentetidspunkt (gemmes, aldrig overskrevet)
                  -> så kan vi senere se, hvordan oddsene bevægede sig frem mod kampen

OddsPapi-struktur (fundet med explore_oddspapi_odds.py):
  bookmakerOdds[<bookmaker>]["markets"]["101"] = 1X2
  outcomes "101" = hjemme, "102" = uafgjort, "103" = ude
  outcomes[...]["players"]["0"]["price"] = odds

Kør:  uv run python src/fetch_weekly.py              (henter fra API'et)
      uv run python src/fetch_weekly.py --offline    (bruger gemte testfiler, 0 API-kald)
"""
import json
import os
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

load_dotenv()
KEY = os.getenv("ODDSPAPI_KEY")
BASE = "https://api.oddspapi.io/v4"
DB = "data/j2.db"

J2_TOURNAMENT = 402
DAYS_AHEAD = 7            # kampprogram: 1 kald uanset antal dage
ODDS_WINDOW_DAYS = 4      # hent kun odds for kampe, der starter inden for 4 dage
                          # (torsdag 06 UTC -> dækker hele weekenden inkl. søndag aften)
                          # (bookmakerne åbner sjældent markeder tidligere -> spildte kald)
BOOKMAKERS = ["pinnacle", "mrgreen.dk", "bet365"]   # skarp, din egen, stor reference
MARKET_1X2 = "101"
OUTCOMES = {"101": "1", "102": "X", "103": "2"}
MAX_CALLS = 25            # sikkerhedsgrænse: gratisplanen giver 250 kald/måned
                          # (1 kald til kampe + 1 pr. kamp; en uge kan have 2 runder = 21 kald)

calls = 0


def api_get(path, params):
    """Ét API-kald med tæller, så en fejl i en løkke ikke brænder hele månedens kvote af."""
    global calls
    if calls >= MAX_CALLS:
        raise RuntimeError(f"Stoppet: nåede MAX_CALLS = {MAX_CALLS}")
    calls += 1
    # 429 = "Too Many Requests": OddsPapi har en cooldown pr. endpoint.
    # Vent og prøv igen (retry med backoff): 5 s, 10 s, 20 s.
    for attempt in range(4):
        r = requests.get(f"{BASE}/{path}", params={"apiKey": KEY, **params}, timeout=60)
        if r.status_code != 429 or attempt == 3:
            break
        wait = float(r.headers.get("Retry-After", 5 * 2 ** attempt))
        print(f"  429 fra OddsPapi ({path}) – venter {wait:.0f} s og prøver igen")
        time.sleep(wait)
    r.raise_for_status()
    time.sleep(1)                                   # høflig pause
    return r.json()


def get_fixtures(offline):
    if offline:
        with open("data/oddspapi_j2_fixtures.json") as f:
            return json.load(f)
    today = date.today()
    return api_get("fixtures", {
        "tournamentId": J2_TOURNAMENT,
        "from": today.isoformat(),
        "to": (today + timedelta(days=DAYS_AHEAD)).isoformat(),
    })


def get_odds(fixture_id, offline):
    if offline:
        with open("data/oddspapi_odds_sample.json") as f:
            sample = json.load(f)
        return sample if sample["fixtureId"] == fixture_id else None
    # bookmakers-filteret gør svaret meget mindre (alle 238 bookmakere fylder ~30 MB)
    return api_get("odds", {"fixtureId": fixture_id, "bookmakers": ",".join(BOOKMAKERS)})


def extract_1x2(odds_json, bookmaker):
    """Træk 1X2-odds for én bookmaker ud af det dybe JSON-svar. None hvis de mangler."""
    bm = odds_json.get("bookmakerOdds", {}).get(bookmaker)
    if not bm:
        return None
    market = bm.get("markets", {}).get(MARKET_1X2)
    if not market:
        return None
    prices = {}
    for outcome_id, label in OUTCOMES.items():
        players = market["outcomes"].get(outcome_id, {}).get("players", {})
        if "0" not in players:
            return None
        prices[label] = players["0"]["price"]
    return {
        "odds_1": prices["1"], "odds_x": prices["X"], "odds_2": prices["2"],
        "market_active": int(bool(market.get("marketActive"))),
    }


def setup_tables(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS op_fixtures (
            fixture_id  TEXT PRIMARY KEY,
            start_time  TEXT,
            home        TEXT,
            away        TEXT,
            status      TEXT,
            updated_at  TEXT
        )""")
    con.execute("""
        CREATE TABLE IF NOT EXISTS odds_snapshots (
            snapshot_at    TEXT,
            fixture_id     TEXT,
            bookmaker      TEXT,
            odds_1         REAL,
            odds_x         REAL,
            odds_2         REAL,
            market_active  INTEGER,
            PRIMARY KEY (fixture_id, bookmaker, snapshot_at)
        )""")


def main(offline):
    snapshot_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fixtures = get_fixtures(offline)

    con = sqlite3.connect(DB)
    setup_tables(con)

    # 1) Gem alle kampe først (koster ingen ekstra kald)
    for fx in fixtures:
        con.execute(
            "INSERT OR REPLACE INTO op_fixtures VALUES (?,?,?,?,?,?)",
            (fx["fixtureId"], fx["startTime"], fx["participant1Name"], fx["participant2Name"],
             fx["statusName"], snapshot_at),
        )
    n_fix = len(fixtures)

    # 2) Hent odds kamp for kamp (ét kald pr. kamp) – kun for kampe tæt på kickoff
    n_odds, missing, skipped = 0, [], 0
    now = datetime.now(timezone.utc)
    for fx in fixtures:
        start = datetime.fromisoformat(fx["startTime"].replace("Z", "+00:00"))
        too_far = start > now + timedelta(days=ODDS_WINDOW_DAYS)
        if not fx.get("hasOdds") or too_far:
            skipped += 1
            continue

        try:
            odds_json = get_odds(fx["fixtureId"], offline)
        except RuntimeError as e:                      # kvote-grænsen: gem det, vi har, og stop
            print(e)
            break
        if odds_json is None:                          # kun i offline-tilstand
            continue
        for bm in BOOKMAKERS:
            o = extract_1x2(odds_json, bm)
            if o is None:
                missing.append(f"{fx['participant1Name']} - {fx['participant2Name']}: {bm}")
                continue
            con.execute(
                "INSERT OR REPLACE INTO odds_snapshots VALUES (?,?,?,?,?,?,?)",
                (snapshot_at, fx["fixtureId"], bm, o["odds_1"], o["odds_x"], o["odds_2"], o["market_active"]),
            )
            n_odds += 1

    con.commit()
    con.close()

    print(f"Snapshot {snapshot_at} {'(OFFLINE)' if offline else ''}")
    print(f"{n_fix} kampe gemt, {n_odds} odds-rækker gemt, {calls} API-kald brugt")
    print(f"{skipped} kampe sprunget over (ingen odds endnu eller mere end {ODDS_WINDOW_DAYS} dage til kickoff)")
    if missing:
        print("Mangler odds:")
        for m in missing:
            print("  ", m)


if __name__ == "__main__":
    main(offline="--offline" in sys.argv)
