import os
import json
from datetime import date, timedelta
import requests
from dotenv import load_dotenv

load_dotenv()
KEY = os.getenv("ODDSPAPI_KEY")
BASE = "https://api.oddspapi.io/v4"
J2 = 402


def cached_get(path, cache, params):
    """Kald API'et én gang og gem svaret. Næste gang læses filen."""
    if not os.path.exists(cache):
        r = requests.get(f"{BASE}/{path}", params={"apiKey": KEY, **params}, timeout=30)
        print(path, "status:", r.status_code)
        with open(cache, "w") as f:
            json.dump(r.json(), f, indent=2, ensure_ascii=False)
    with open(cache) as f:
        return json.load(f)


# Kald 2: J2-kampe de næste 10 dage
today = date.today()
fixtures = cached_get("fixtures", "data/oddspapi_j2_fixtures.json",
                      {"tournamentId": J2, "from": today.isoformat(),
                       "to": (today + timedelta(days=10)).isoformat()})
print(type(fixtures).__name__, "med", len(fixtures), "elementer")
print(json.dumps(fixtures[0], indent=2, ensure_ascii=False)[:1500])

# Kald 3: odds for den første kamp
fid = fixtures[0]["fixtureId"]
odds = cached_get("odds", "data/oddspapi_odds_sample.json", {"fixtureId": fid})
print("\nNøgler i odds-svaret:", list(odds.keys()) if isinstance(odds, dict) else type(odds).__name__)
print(json.dumps(odds, indent=2, ensure_ascii=False)[:2500])
# Kald 4: J2-kampe fra den seneste uge – har de resultater?
past = cached_get("fixtures", "data/oddspapi_j2_past.json",
                  {"tournamentId": J2, "from": (today - timedelta(days=7)).isoformat(),
                   "to": today.isoformat()})
print("\nSpillede kampe:", len(past))
ended = [f for f in past if f.get("statusName") != "Pre-Game"]
print("Heraf ikke 'Pre-Game':", len(ended))
print(json.dumps((ended or past)[0], indent=2, ensure_ascii=False)[:2500])

# Kald 5: resultat for én spillet kamp – hvilken periode er slutresultatet?
done_fx = [f for f in past if f.get("statusName") == "Finished"][0]
print("\nKamp:", done_fx["participant1Name"], "-", done_fx["participant2Name"], done_fx["startTime"])
score = cached_get("scores", "data/oddspapi_score_sample.json", {"fixtureId": done_fx["fixtureId"]})
print(json.dumps(score, indent=2, ensure_ascii=False)[:2000])
