import os
import requests
from dotenv import load_dotenv

load_dotenv()
r = requests.get(
    "https://v3.football.api-sports.io/odds",
    headers={"x-apisports-key": os.getenv("APIFOOTBALL_KEY")},
    params={"league": 99, "season": 2024},
)
data = r.json()
print("Fejl:", data["errors"])
print("Resultater:", data["results"], "| sider:", data["paging"])
if data["response"]:
    first = data["response"][0]
    print("Fixture:", first["fixture"]["id"], first["fixture"]["date"])
    for bm in first["bookmakers"][:3]:
        print(" ", bm["name"], [b["name"] for b in bm["bets"]][:5])