"""Hent resultater for spillede J2-kampe fra OddsPapi og gem dem i SQLite.

Erstatter den manuelle indtastning af resultater i Excel.
Excel-kampene (manual_matches) bruges stadig som sæsonens udgangspunkt (runde 1-10),
og fra runde 11 kommer resultaterne herfra. model.load_current_season() samler dem.

To endpoints:
  /fixtures (1 kald)        -> hvilke kampe er spillet de sidste DAYS_BACK dage
  /scores   (1 kald/kamp)   -> slutresultatet; vi bruger perioden "fulltime" (90 min)

Kun kampe, vi IKKE allerede har et resultat for, bliver slået op – så en ny kørsel
koster kun kald for nye kampe.

Kør:  uv run python src/fetch_results.py
      uv run python src/fetch_results.py --offline   (gemte testfiler, 0 kald)
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
DAYS_BACK = 7
MAX_CALLS = 15
calls = 0


def api_get(path, params):
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
    time.sleep(1.1)                     # /scores har en cooldown på 1000 ms
    return r.json()


def get_past_fixtures(offline):
    if offline:
        with open("data/oddspapi_j2_past.json") as f:
            return json.load(f)
    today = date.today()
    return api_get("fixtures", {"tournamentId": J2_TOURNAMENT,
                                "from": (today - timedelta(days=DAYS_BACK)).isoformat(),
                                "to": today.isoformat()})


def get_score(fixture_id, offline):
    if offline:
        with open("data/oddspapi_score_sample.json") as f:
            s = json.load(f)
        return s if s["fixtureId"] == fixture_id else None
    return api_get("scores", {"fixtureId": fixture_id})


def final_score(score_json):
    """Slutresultat efter 90 min. 'fulltime' foretrækkes; 'result' bruges som reserve."""
    periods = score_json.get("scores", {}).get("periods", {})
    p = periods.get("fulltime") or periods.get("result")
    if not p:
        return None
    return int(p["participant1Score"]), int(p["participant2Score"])


def main(offline):
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    con = sqlite3.connect(DB)
    con.execute("""
        CREATE TABLE IF NOT EXISTS op_results (
            fixture_id  TEXT PRIMARY KEY,
            start_time  TEXT,
            home        TEXT,
            away        TEXT,
            home_goals  INTEGER,
            away_goals  INTEGER,
            fetched_at  TEXT
        )""")
    have = {r[0] for r in con.execute("SELECT fixture_id FROM op_results")}

    past = get_past_fixtures(offline)
    finished = [f for f in past if f.get("statusName") == "Finished" and f["fixtureId"] not in have]

    saved, problems = 0, []
    for fx in finished:
        try:
            s = get_score(fx["fixtureId"], offline)
        except RuntimeError as e:
            print(e)
            break
        if s is None:                                    # kun offline
            continue
        fs = final_score(s)
        label = f"{fx['participant1Name']} - {fx['participant2Name']}"
        if fs is None:
            problems.append(f"{label}: ingen 'fulltime'/'result' i svaret")
            continue
        con.execute("INSERT OR REPLACE INTO op_results VALUES (?,?,?,?,?,?,?)",
                    (fx["fixtureId"], fx["startTime"], fx["participant1Name"], fx["participant2Name"],
                     fs[0], fs[1], fetched_at))
        saved += 1
        print(f"  {label}: {fs[0]}-{fs[1]}")

    # Hold uden kobling i team_map -> name_agent.py skal køres igen
    unmapped = [r[0] for r in con.execute("""
        SELECT DISTINCT name FROM (SELECT home AS name FROM op_results UNION SELECT away FROM op_results)
        WHERE name NOT IN (SELECT name FROM team_map WHERE source = 'oddspapi')""")]
    con.commit()
    con.close()

    print(f"\n{len(past)} kampe i perioden, {len(finished)} nye spillede, {saved} resultater gemt, "
          f"{calls} API-kald brugt {'(OFFLINE)' if offline else ''}")
    for p in problems:
        print("PROBLEM:", p)
    if unmapped:
        print(f"Ukendte holdnavne (kør name_agent.py): {unmapped}")


if __name__ == "__main__":
    main(offline="--offline" in sys.argv)
