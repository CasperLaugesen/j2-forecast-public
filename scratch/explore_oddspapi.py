import os
import json
from datetime import date, timedelta
import requests
from dotenv import load_dotenv

load_dotenv()
KEY = os.getenv("ODDSPAPI_KEY")
BASE = "https://api.oddspapi.io/v4"

# Kald 1: find japanske turneringer
r = requests.get(f"{BASE}/tournaments", params={"apiKey": KEY, "sportId": 10}, timeout=30)
print("Status:", r.status_code)
tournaments = r.json()
japan = [t for t in tournaments if "japan" in json.dumps(t).lower()]
for t in japan:
    print(t)