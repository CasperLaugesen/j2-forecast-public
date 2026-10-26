import os
import requests
from dotenv import load_dotenv

load_dotenv()                          # læser .env ind
key = os.getenv("APIFOOTBALL_KEY")

r = requests.get(
    "https://v3.football.api-sports.io/leagues",
    headers={"x-apisports-key": key},
    params={"country": "Japan"},
)

print("Status:", r.status_code)        # 200 = OK
data = r.json()
print("Fejl fra API:", data["errors"])

for item in data["response"]:
    league = item["league"]
    seasons = [s["year"] for s in item["seasons"]]
    print(league["id"], league["name"], item["country"]["name"], seasons[-3:])