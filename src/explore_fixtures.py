import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()
key = os.getenv("APIFOOTBALL_KEY")

r = requests.get(
    "https://v3.football.api-sports.io/fixtures",
    headers={"x-apisports-key": key},
    params={"league": 99, "season": 2024},
)
data = r.json()
print("Fejl fra API:", data["errors"])
print("Antal kampe:", data["results"])

os.makedirs("data", exist_ok=True)
with open("data/fixtures_99_2026.json", "w") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

for fx in data["response"][:5]:
    print(fx["fixture"]["date"][:10],
          fx["teams"]["home"]["name"], fx["goals"]["home"], "-",
          fx["goals"]["away"], fx["teams"]["away"]["name"])