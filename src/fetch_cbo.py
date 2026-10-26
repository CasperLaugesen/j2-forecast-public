import os
import time
import requests

SEASONS = [2022, 2023, 2024]          # samme sæsoner som dine J2-resultater fra API'et
URL = "https://checkbestodds.com/football-odds/archive-japan/{}"
OUT = "data/cbo"


def main():
    os.makedirs(OUT, exist_ok=True)
    for season in SEASONS:
        r = requests.get(
            URL.format(season),
            headers={"User-Agent": "j2-forecast student project (personal analysis)"},
            timeout=30,
        )
        r.raise_for_status()
        path = f"{OUT}/japan_{season}.html"
        with open(path, "w", encoding="utf-8") as f:
            f.write(r.text)
        print(season, r.status_code, len(r.text), "tegn ->", path)
        time.sleep(5)                 # høflig pause mellem forespørgsler


if __name__ == "__main__":
    main()